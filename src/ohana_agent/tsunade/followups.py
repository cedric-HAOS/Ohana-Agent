"""One authorized log collection followed by one bounded Katsuyu review."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from ohana_agent.contracts.administration import LogsInvestigateParameters
from ohana_agent.jobs.repository import DistributedJobRepository
from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository

LOCAL_TIMEZONE = ZoneInfo("Europe/Paris")


class TsunadeFollowupService:
    """Map an AI suggestion to an existing capability; never execute AI text."""

    def __init__(
        self,
        incidents: TsunadeIncidentRepository,
        jobs: DistributedJobRepository,
        expertise: TsunadeExpertiseService,
        create_job: Callable[[dict[str, Any]], Any],
        policy: Callable[[], tuple[bool, tuple[str, ...], int, int]],
        notify: Callable[[dict[str, Any]], None],
        *,
        automatic_read_only: bool = False,
    ) -> None:
        self.incidents = incidents
        self.jobs = jobs
        self.expertise = expertise
        self.create_job = create_job
        self.policy = policy
        self.notify = notify
        self.automatic_read_only = automatic_read_only

    def consider(self, job: Any) -> None:
        """Offer one concrete collection per unchanged set of observations."""
        incident_id = job.parameters.get("incident_id")
        result = job.result or {}
        suggestions = result.get("recommended_investigation", [])
        if not incident_id or not suggestions:
            return
        evidence = job.parameters.get("evidence", [])
        if any(
            item.get("source")
            == (
                "diagnostics.configuration"
                if self.automatic_read_only
                else "investigation.followup"
            )
            for item in evidence
        ):
            return  # A follow-up review never starts another investigation loop.
        incident = self.incidents.get(incident_id)
        if incident.state != "active":
            return
        previous = incident.followup or {}
        if previous.get("status") == "refused":
            return
        if previous.get("status") == "pending":
            request = self.incidents.get_user_request(previous["request_id"])
            if request.deferred_until is not None:
                return
        for item in evidence:
            if item.get("source") == "shikamaru.observation":
                try:
                    observed = json.loads(item["content"])["last_observed_at"]
                    if datetime.fromisoformat(observed) < incident.last_observed_at:
                        return
                except (ValueError, TypeError, KeyError):
                    return
        enabled, sources, max_bytes, timeout = self.policy()
        supported = (
            enabled
            and incident.capability_id == "logs.health"
            and incident.node_id in sources
            and (
                self.automatic_read_only
                or any(
                    word in " ".join(suggestions).casefold()
                    for word in ("journal", "log", "trace", "collect")
                )
            )
        )
        findings = incident.context.get("findings", [])
        # Categories are literal strings present in logs, unlike normalized
        # signatures which can contain placeholders and occurrence counts.
        patterns = {
            "timeout": "timeout",
            "exception": "exception",
            "mqtt": "mqtt",
            "network": "connection",
            "restart": "restart",
            "serial": "serial",
            "zwave": "zwave",
            "automation": "automation",
        }
        pattern = next(
            (
                patterns[f["category"]]
                for f in findings
                if f.get("category") in patterns
            ),
            None,
        )
        if pattern is None:
            pattern = next(
                (
                    ref.strip()[:160]
                    for f in findings
                    for ref in f.get("references", [])
                    if isinstance(ref, str) and ref.strip()
                ),
                None,
            )
        if not supported or not pattern or any(c in pattern for c in "\r\n\0"):
            if not any(
                e.payload.get("unsupported_job_id") == str(job.job_id)
                for e in incident.events
            ):
                self.incidents.append_record(
                    incident_id,
                    {
                        "kind": "action",
                        "summary": "Investigation à préciser : aucune collecte ciblée "
                        "autorisable ne correspond aux éléments disponibles.",
                        "payload": {
                            "unsupported_job_id": str(job.job_id),
                            "status": "unsupported",
                            "authorized": False,
                        },
                    },
                )
            return
        basis = hashlib.sha256(
            json.dumps(
                [
                    (f.get("signature"), f.get("occurrences"), f.get("severity"))
                    for f in findings
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if self.automatic_read_only:
            basis += ":read-only-v2"
        proposal = self.incidents.propose_followup(
            str(incident_id),
            str(job.job_id),
            basis,
            {
                "operation": "logs.investigate",
                "source": incident.node_id,
                "pattern": pattern,
                "max_bytes": max_bytes,
                "timeout": timeout,
                "read_only_probes": self.automatic_read_only,
                "reason": "Vérifier les anomalies observées avec une collecte ciblée "
                "avant de réévaluer les hypothèses de Katsuyu.",
            },
        )
        if not proposal and self.automatic_read_only:
            latest = self.incidents.latest_followup(str(incident_id))
            if latest and latest["status"] == "pending":
                request = self.incidents.get_user_request(latest["request_id"])
                if request.deferred_until is None:
                    self.respond(
                        latest["request_id"], "tsunade", "AUTHORIZE", automatic=True
                    )
            return
        if proposal:
            if self.automatic_read_only:
                self.respond(
                    proposal["request_id"], "tsunade", "AUTHORIZE", automatic=True
                )
                return
            self.notify(
                {
                    "schema_version": 1,
                    "notification_id": f"investigation-{proposal['request_id']}",
                    "type": "DECISION_REQUIRED",
                    "title": "Tsunade propose une investigation",
                    "message": "Une collecte ciblée attend votre autorisation.",
                    "incident_id": str(incident_id),
                    "occurred_at": proposal["created_at"],
                }
            )

    def respond(
        self, request_id: str, device_id: str, choice: str, *, automatic: bool = False
    ) -> object:
        request = self.incidents.get_user_request(request_id)
        followup = self.incidents.get_followup(request_id)
        if request.state == "answered" and request.answer == choice:
            # Response retries resume the same durable intent, never a new job.
            self.resume()
            return request
        job = None
        if choice == "AUTHORIZE":
            self._validate_policy(followup)
            if self.jobs.active_for_incident(
                "logs.investigate", followup["incident_id"]
            ):
                raise ValueError("Une collecte est déjà en cours pour cet incident")
            now = datetime.now(LOCAL_TIMEZONE)
            plan = followup["plan"]
            parameters = LogsInvestigateParameters(
                source=plan["source"],
                pattern=plan["pattern"],
                window_started_at=now - timedelta(hours=2),
                window_ended_at=now,
                max_bytes=plan["max_bytes"],
                incident_id=followup["incident_id"],
            )
            job = {
                "protocol_version": 1,
                "job_id": str(uuid4()),
                "type": "logs.investigate",
                "created_at": now.isoformat(),
                "parameters": parameters.model_dump(mode="json"),
                "timeout": plan["timeout"],
            }
        self.incidents.answer_followup(
            request_id, choice, device_id, job, automatic=automatic
        )
        self.resume()
        return self.incidents.get_user_request(request_id)

    def _validate_policy(self, followup: dict[str, Any]) -> None:
        enabled, sources, max_bytes, timeout = self.policy()
        plan = followup["plan"]
        incident = self.incidents.get(followup["incident_id"])
        if (
            not enabled
            or plan["source"] not in sources
            or incident.state != "active"
            or incident.node_id != plan["source"]
            or plan["max_bytes"] > max_bytes
            or plan["timeout"] > timeout
        ):
            raise ValueError(
                "Le périmètre de collecte n’est plus autorisé ; "
                "la demande doit être réévaluée."
            )

    def resume(self) -> None:
        """Recover the gap between committed intent and distributed job creation."""
        for followup in self.incidents.unfinished_followups():
            payload = (
                followup["review"]
                if followup["status"] == "reviewing"
                else followup["job"]
            )
            if payload is None:
                continue
            try:
                self.jobs.get(payload["job_id"])
            except LookupError:
                try:
                    self._validate_policy(followup)
                    if payload["type"] == "ai.inference":
                        active = self.jobs.active_for_incident(
                            "ai.inference", followup["incident_id"]
                        )
                        if active is not None:
                            continue
                    self.create_job(payload)
                except (LookupError, ValueError) as error:
                    self.incidents.update_followup(
                        followup["request_id"],
                        "failed",
                        f"Investigation interrompue : {str(error)[:400]}",
                    )
                    continue
            if followup["status"] == "authorized":
                self.incidents.update_followup(
                    followup["request_id"],
                    "queued",
                    "Collecte complémentaire en cours ou en attente de Katsuyu.",
                )

    def completed(self, job: Any) -> None:
        """Persist the second job before dispatch; failed collections are explicit."""
        for followup in self.incidents.unfinished_followups():
            collection_id = (followup["job"] or {}).get("job_id")
            review_id = (followup["review"] or {}).get("job_id")
            if str(job.job_id) not in {collection_id, review_id}:
                continue
            if job.status.value != "SUCCEEDED":
                self.incidents.update_followup(
                    followup["request_id"],
                    "failed",
                    f"Investigation complémentaire non aboutie ({job.status.value}).",
                )
            elif str(job.job_id) == review_id:
                incomplete = (job.result or {}).get("verdict") == "INSUFFICIENT_CONTEXT"
                self.incidents.update_followup(
                    followup["request_id"],
                    "incomplete" if incomplete else "completed",
                    "Collecte réévaluée ; les éléments restent insuffisants."
                    if incomplete
                    else "Tsunade a réévalué la collecte complémentaire.",
                )
            elif followup["status"] != "reviewing":
                # KO means matching anomalies, not a failed collection. Transport
                # failures are represented by the distributed job status above.
                incident = self.incidents.get(followup["incident_id"])
                if incident.state != "active":
                    self.incidents.update_followup(
                        followup["request_id"],
                        "cancelled",
                        "Incident résolu ; aucune réévaluation nécessaire.",
                    )
                    continue
                review = self.expertise.prepare_followup_review(
                    incident, followup["request_id"], job
                )
                if self.automatic_read_only:
                    try:
                        snapshot = self.expertise.investigations.read_only_snapshot(
                            incident.node_id
                        )
                    except Exception as error:
                        snapshot = {
                            "status": "unavailable",
                            "error": type(error).__name__,
                        }
                    review["parameters"]["evidence"].append(
                        {
                            "source": "diagnostics.read_only",
                            "content": json.dumps(snapshot, ensure_ascii=False),
                        }
                    )
                    review["parameters"]["evidence"].append(
                        {
                            "source": "diagnostics.configuration",
                            "content": "Configuration et état Supervisor examinés dans "
                            "diagnostics.read_only.configuration_inspection ; voir les "
                            "limites et indisponibilités explicites. Ne redemande pas "
                            "une lecture déjà faite. Une présence matérielle ne prouve "
                            "pas l’ouverture du port série par le processus.",
                        }
                    )
                    review["parameters"]["question"] += (
                        " Distingue chaque lieu de mesure. Exploite les résultats "
                        "DNS/TCP/HTTP et système joints ; ne redemande pas les tests "
                        "déjà exécutés. Précise les tests manquants et leur cible."
                    )
                    self.incidents.append_record(
                        incident.incident_id,
                        {
                            "kind": "investigation",
                            "summary": "Tests en lecture seule depuis Agent : "
                            "DNS, TCP, HTTP et état de l’hôte.",
                            "payload": {
                                "source": "read_only_policy",
                                "collection_job_id": str(job.job_id),
                                "result": snapshot,
                            },
                        },
                    )
                self.incidents.update_followup(
                    followup["request_id"],
                    "reviewing",
                    "Collecte reçue ; réévaluation Katsuyu en cours ou en attente.",
                    review=review,
                )
        self.resume()
