"""Bounded Tsunade diagnostic cycle with optional Katsuyu AI escalation."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from threading import Lock, Thread
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from ohana_agent.tsunade.diagnostic_basis import incident_basis_fingerprint
from ohana_agent.tsunade.evidence_privacy import (
    redact_sensitive_value,
)
from ohana_agent.tsunade.expertise_ai import TsunadeAIExpertise
from ohana_agent.tsunade.expertise_catalog import (
    KNOWN_PROCEDURES,
    KnownProcedure,
    TsunadeDecisionResult,
    TsunadeExpertiseConflictError,
    TsunadeExpertiseOutcome,
    _teleinformation_addon_state,
)
from ohana_agent.tsunade.expertise_logs import TsunadeLogExpertise
from ohana_agent.tsunade.incident_correlation import (
    active_upstream_incident,
    declared_dependencies,
)
from ohana_agent.tsunade.incident_models import (
    TsunadeExperience,
    TsunadeIncident,
)
from ohana_agent.tsunade.incidents import (
    TsunadeIncidentRepository,
)
from ohana_agent.tsunade.investigations import (
    InvestigationExecutor,
    InvestigationResult,
    investigation_summary,
    probe_failed,
)

LOGGER = logging.getLogger(__name__)


class TsunadeExpertiseService(TsunadeLogExpertise, TsunadeAIExpertise):
    """Run finite probes first and request local AI only when still insufficient."""

    def __init__(
        self,
        *,
        incidents: TsunadeIncidentRepository,
        investigations: InvestigationExecutor,
        ai_dispatcher: Callable[[dict[str, Any]], object | None] | None = None,
    ) -> None:
        self.incidents = incidents
        self.investigations = investigations
        self.ai_dispatcher = ai_dispatcher
        self.repair_proposer: Callable[[UUID], object] | None = None
        self._lock = Lock()
        self._inflight: set[str] = set()

    def set_ai_dispatcher(
        self, dispatcher: Callable[[dict[str, Any]], object | None]
    ) -> None:
        self.ai_dispatcher = dispatcher

    def set_repair_proposer(self, proposer: Callable[[UUID], object]) -> None:
        self.repair_proposer = proposer

    def start(
        self,
        incident_id: UUID | str,
        *,
        log_result: dict[str, Any] | None = None,
    ) -> None:
        """Run the bounded cycle outside worker completion and observation threads."""

        def run() -> None:
            try:
                self.diagnose(incident_id, log_result=log_result)
            except Exception:
                LOGGER.exception(
                    "Tsunade expertise failed for incident %s", incident_id
                )

        Thread(
            target=run,
            name=f"tsunade-expertise-{str(incident_id)[:8]}",
            daemon=True,
        ).start()

    def diagnose(
        self,
        incident_id: UUID | str,
        *,
        log_result: dict[str, Any] | None = None,
        operator_requested: bool = False,
    ) -> TsunadeExpertiseOutcome:
        key = str(incident_id)
        with self._lock:
            if key in self._inflight:
                raise TsunadeExpertiseConflictError(
                    "Tsunade expertise is already running for this incident"
                )
            self._inflight.add(key)
        try:
            incident = self.incidents.get(incident_id)
            if incident.state != "active":
                raise ValueError("Tsunade diagnoses only active incidents")
            if incident.expertise_state == "ai_queued":
                raise TsunadeExpertiseConflictError(
                    "Katsuyu AI is already queued for this incident"
                )
            procedure = self._known_procedure(incident)
            experiences = self.incidents.matching_experiences(incident)
            # A completed log collection is already bounded evidence. Reviewing it
            # must not block worker completion on another round of network probes.
            investigation_results = (
                []
                if log_result is not None and incident.capability_id == "logs.health"
                else self._run_investigations(incident, procedure)
            )
            facts = self._facts(incident, investigation_results, log_result)
            failures = [
                result for result in investigation_results if probe_failed(result)
            ]
            if procedure is not None and failures:
                outcome = TsunadeExpertiseOutcome(
                    incident_id=incident.incident_id,
                    status="DETERMINISTIC",
                    known_procedure=True,
                    diagnosis=procedure.diagnosis,
                    facts=facts,
                    proposals=[
                        *procedure.proposals,
                        *self._experience_proposals(experiences),
                    ][:16],
                    decision="action_required",
                    decision_source="deterministic",
                    confidence=1.0,
                )
                self._record_deterministic(outcome, failures)
                self._propose_known_repair(incident.incident_id)
                return outcome

            if incident.capability_id == "logs.health":
                decision = self._log_decision(incident, log_result)

                if decision.decision in {"stable", "watch"} and not operator_requested:
                    outcome = TsunadeExpertiseOutcome(
                        incident_id=incident.incident_id,
                        status="DETERMINISTIC",
                        known_procedure=procedure is not None,
                        diagnosis=decision.conclusion,
                        facts=facts,
                        proposals=[],
                        decision=decision.decision,
                        decision_source=decision.source,
                        confidence=decision.confidence,
                    )
                    self._record_decision(
                        incident.incident_id,
                        decision,
                        facts=facts,
                        cycle_status="deterministic_decision",
                    )
                    return outcome

            supervisor_evidence = None
            # A stale direct HTTP teleinformation feed can have a deterministic
            # explanation available from the node's read-only configuration
            # inspection. Check it before escalating to Katsuyu.
            if (
                incident.capability_id == "teleinformation.freshness"
                and incident.context.get("mode") == "direct_http"
            ):
                try:
                    diagnostics = self.investigations.read_only_snapshot(
                        incident.node_id
                    )
                except Exception as error:
                    LOGGER.warning(
                        "Read-only inspection failed for incident %s: %s",
                        incident.incident_id,
                        type(error).__name__,
                    )
                    diagnostics = {
                        "status": "unavailable",
                        "error": type(error).__name__,
                    }

                snapshot = diagnostics if isinstance(diagnostics, dict) else {}
                supervisor_evidence = json.loads(
                    self._bounded_json(
                        {
                            "node": incident.node_id,
                            "observed_at": snapshot.get("observed_at"),
                            "recorded_at": datetime.now(
                                ZoneInfo("Europe/Paris")
                            ).isoformat(),
                            "basis_observed_at": incident.last_observed_at.isoformat(),
                            "status": snapshot.get("status"),
                            "error": snapshot.get("error"),
                            "reason": snapshot.get("reason"),
                            "configuration_inspection": snapshot.get(
                                "configuration_inspection",
                                {
                                    "status": "unavailable",
                                    "reason": "Inspection absente",
                                },
                            ),
                        }
                    )
                )
                self.incidents.append_record(
                    incident.incident_id,
                    {
                        "kind": "investigation",
                        "summary": "Tsunade a inspecté le Supervisor Téléinformation.",
                        "payload": {
                            "source": "supervisor.teleinformation",
                            **supervisor_evidence,
                        },
                    },
                )

                addon_state, addon_id = _teleinformation_addon_state(
                    incident,
                    diagnostics,
                )

                if addon_state in {"stopped", "error"}:
                    addon_name = addon_id or "teleinfo2mqtt"

                    if addon_state == "stopped":
                        state_description = "arrêté"
                    else:
                        state_description = "dans un état d’erreur"

                    decision = TsunadeDecisionResult(
                        decision="investigate",
                        source="deterministic",
                        conclusion=(
                            f"Le Supervisor de {incident.node_id.upper()} "
                            f"indique que l’add-on {addon_name} est "
                            f"{state_description}. "
                            "En mode direct_http, cet état non opérationnel "
                            "explique l’absence de nouvelles trames "
                            "Téléinformation vers Agent."
                        ),
                        reason=(
                            "L’état courant fourni par le Supervisor "
                            f"pour {addon_name} est « {addon_state} »."
                        ),
                        confidence=1.0,
                        recommended_action=(
                            f"Vérifier pourquoi l’add-on {addon_name} "
                            "n’est pas opérationnel avant toute remise en service."
                        ),
                        reevaluate_after="next_observation",
                    )

                    deterministic_facts = [
                        *facts,
                        (
                            f"Supervisor : l’add-on {addon_name} "
                            f"est dans l’état « {addon_state} » "
                            f"sur {incident.node_id.upper()}."
                        ),
                    ][:32]

                    outcome = TsunadeExpertiseOutcome(
                        incident_id=incident.incident_id,
                        status="DETERMINISTIC",
                        known_procedure=procedure is not None,
                        diagnosis=decision.conclusion,
                        facts=deterministic_facts,
                        proposals=[decision.recommended_action],
                        decision=decision.decision,
                        decision_source=decision.source,
                        confidence=decision.confidence,
                    )

                    self._record_decision(
                        incident.incident_id,
                        decision,
                        facts=deterministic_facts,
                        cycle_status="deterministic_decision",
                        epistemic_status="confirmed_by_supervisor",
                        diagnostic_level="CONFIRMED",
                        basis_observed_at=incident.last_observed_at.isoformat(),
                    )

                    return outcome

            # A declared upstream service with its own active incident explains
            # the symptom well enough to avoid an AI expertise (failure #3:
            # sun-01 telemetry lost while the MQTT broker was down).
            upstream = None if operator_requested else self._active_upstream(incident)
            if upstream is not None:
                return self._record_upstream_correlation(
                    incident, upstream, facts, procedure
                )

            parameters = self._ai_parameters(
                incident,
                procedure,
                investigation_results,
                log_result,
                experiences,
                supervisor_evidence=supervisor_evidence,
            )
            job = (
                self.ai_dispatcher(parameters)
                if self.ai_dispatcher is not None
                else None
            )
            job_id = getattr(job, "job_id", None)
            if job_id is None:
                outcome = TsunadeExpertiseOutcome(
                    incident_id=incident.incident_id,
                    status="INSUFFICIENT_CONTEXT",
                    known_procedure=procedure is not None,
                    diagnosis=(
                        "Les éléments déterministes n’expliquent pas encore l’anomalie "
                        "et aucun worker Katsuyu AI compatible n’est disponible."
                    ),
                    facts=facts,
                    proposals=(
                        [
                            *(procedure.proposals if procedure else ()),
                            *self._experience_proposals(experiences),
                        ][:16]
                    ),
                    decision="watch",
                    decision_source="fallback",
                )
                self.incidents.append_record(
                    incident.incident_id,
                    {
                        "kind": "diagnostic",
                        "summary": outcome.diagnosis,
                        "payload": {
                            "cycle_status": "insufficient_context",
                            "facts": facts,
                            "decision": outcome.decision,
                            "decision_source": outcome.decision_source,
                            "epistemic_status": "insufficient_context",
                            "diagnostic_level": "INSUFFICIENT_CONTEXT",
                            "confirmation_gap": [
                                "Aucune preuve déterministe ne confirme encore la"
                                " cause.",
                                "Aucune expertise Katsuyu compatible n'a pu être"
                                " mise en file.",
                            ],
                            "verdict": "INSUFFICIENT_CONTEXT",
                            "conclusion": outcome.diagnosis,
                            "reason": (
                                "Les contrôles disponibles ne confirment pas la cause. "
                                "Aucune expertise Katsuyu n’a pu être mise en file."
                            ),
                            "recommended_action": (
                                "Maintenir la surveillance ; vérifier les limites des "
                                "sondes et la disponibilité de Katsuyu avant de "
                                "demander une nouvelle expertise."
                            ),
                            "basis_observed_at": incident.last_observed_at.isoformat(),
                        },
                    },
                )
                return outcome

            outcome = TsunadeExpertiseOutcome(
                incident_id=incident.incident_id,
                status="AI_QUEUED",
                known_procedure=procedure is not None,
                diagnosis=(
                    "Les éléments déterministes sont insuffisants ; "
                    "une analyse Katsuyu AI a été demandée."
                ),
                facts=facts,
                proposals=[
                    *(procedure.proposals if procedure else ()),
                    *self._experience_proposals(experiences),
                ][:16],
                ai_job_id=job_id,
                decision="investigate",
                decision_source="deterministic",
                confidence=0.90,
            )
            self.incidents.append_record(
                incident.incident_id,
                {
                    "kind": "diagnostic",
                    "summary": outcome.diagnosis,
                    "payload": {
                        "cycle_status": "ai_queued",
                        "trigger": (
                            "operator_request"
                            if operator_requested
                            else "automatic_escalation"
                        ),
                        "facts": facts,
                        "ai_job_id": str(job_id),
                        "reviewed_log_findings": [
                            fingerprint
                            for finding in (log_result or incident.context).get(
                                "findings", []
                            )[:64]
                            if (fingerprint := self._log_finding_fingerprint(finding))
                        ]
                        if incident.capability_id == "logs.health"
                        else [],
                        "reviewed_log_signatures": self._log_signature_markers(
                            (log_result or incident.context).get("findings", [])
                        )
                        if incident.capability_id == "logs.health"
                        else {},
                        "decision": "investigate",
                        "decision_source": "deterministic",
                        "conclusion": (
                            "Les éléments disponibles justifient une analyse "
                            "corrélée complémentaire."
                        ),
                        "confidence": 0.90,
                        "recommended_action": (
                            "Utiliser Katsuyu AI comme aide à l’interprétation "
                            "avant toute action."
                        ),
                    },
                },
            )
            return outcome
        finally:
            with self._lock:
                self._inflight.discard(key)

    def _run_investigations(
        self,
        incident: TsunadeIncident,
        procedure: KnownProcedure | None,
    ) -> list[InvestigationResult]:
        results: list[InvestigationResult] = []
        for operation in procedure.operations if procedure is not None else ():
            result = self.investigations.execute(
                {
                    "operation": operation,
                    "parameters": {},
                    "timeout_seconds": self._operation_timeout(operation),
                    "incident_id": str(incident.incident_id),
                }
            )
            results.append(result)
            self.incidents.append_record(
                incident.incident_id,
                {
                    "kind": "investigation",
                    "summary": investigation_summary(result),
                    "payload": result.model_dump(mode="json"),
                },
            )
        return results

    def _propose_known_repair(self, incident_id: UUID) -> None:
        """Offer the catalogue repair; only a human authorization can run it."""
        if self.repair_proposer is None:
            return
        try:
            self.repair_proposer(incident_id)
        except (LookupError, ValueError) as error:
            # Most confirmed diagnoses have no known repair: that is expected.
            LOGGER.info("No supervised repair proposed for %s: %s", incident_id, error)
        except Exception:
            LOGGER.exception("Supervised repair proposal failed for %s", incident_id)

    def _active_upstream(self, incident: TsunadeIncident) -> TsunadeIncident | None:
        reader = getattr(self.investigations, "infrastructure_reader", None)
        if reader is None:
            return None
        try:
            dependencies = declared_dependencies(reader(), incident.service_id)
            if not dependencies:
                return None
            return active_upstream_incident(
                incident,
                dependencies,
                self.incidents.list(state="active", limit=500),
            )
        except Exception as error:
            # Correlation only saves an expertise; its failure must not block one.
            LOGGER.warning(
                "Upstream correlation unavailable for incident %s: %s",
                incident.incident_id,
                type(error).__name__,
            )
            return None

    def _record_upstream_correlation(
        self,
        incident: TsunadeIncident,
        upstream: TsunadeIncident,
        facts: list[str],
        procedure: KnownProcedure | None,
    ) -> TsunadeExpertiseOutcome:
        upstream_label = f"{upstream.service_id} ({upstream.node_id.upper()})"
        started_at = upstream.started_at.astimezone(ZoneInfo("Europe/Paris"))
        decision = TsunadeDecisionResult(
            decision="watch",
            source="deterministic",
            conclusion=(
                f"Symptôme rattaché à l’incident amont actif sur {upstream_label}. "
                f"L’architecture déclare que {incident.service_id} dépend de "
                f"{upstream.service_id}."
            ),
            reason=(
                f"L’incident {upstream.capability_id} de {upstream_label} est actif "
                f"depuis {started_at:%H:%M:%S} ({upstream.message}). "
                "Aucune expertise Katsuyu n’est demandée tant qu’il reste actif ; "
                "la corrélation ne prouve pas à elle seule la cause."
            ),
            confidence=0.8,
            recommended_action=(
                f"Traiter l’incident amont sur {upstream_label}. Si ce symptôme "
                "persiste après sa résolution, Tsunade le réévalue à la "
                "prochaine observation."
            ),
            reevaluate_after="upstream_resolution",
        )
        correlated_facts = [
            *facts,
            (
                f"Incident amont actif : {upstream.service_id} / "
                f"{upstream.capability_id} sur {upstream.node_id.upper()}"
            ),
        ][:32]
        self._record_decision(
            incident.incident_id,
            decision,
            facts=correlated_facts,
            cycle_status="deterministic_decision",
            epistemic_status="correlated_with_upstream",
            diagnostic_level="PROBABLE",
            basis_observed_at=incident.last_observed_at.isoformat(),
            extra={"upstream_incident_id": str(upstream.incident_id)},
        )
        self.incidents.append_record(
            upstream.incident_id,
            {
                "kind": "investigation",
                "summary": (
                    "Symptôme aval rattaché : "
                    f"{incident.service_id} / {incident.capability_id} "
                    f"sur {incident.node_id.upper()}."
                ),
                "payload": {
                    "source": "tsunade.correlation",
                    "downstream_incident_id": str(incident.incident_id),
                },
            },
        )
        return TsunadeExpertiseOutcome(
            incident_id=incident.incident_id,
            status="DETERMINISTIC",
            known_procedure=procedure is not None,
            diagnosis=decision.conclusion,
            facts=correlated_facts,
            proposals=[decision.recommended_action],
            decision=decision.decision,
            decision_source=decision.source,
            confidence=decision.confidence,
        )

    def _record_decision(
        self,
        incident_id: UUID | str,
        decision: TsunadeDecisionResult,
        *,
        facts: list[str],
        cycle_status: str,
        epistemic_status: str | None = None,
        diagnostic_level: str | None = None,
        basis_observed_at: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        incident = self.incidents.get(incident_id)

        payload: dict[str, Any] = {
            "cycle_status": cycle_status,
            "decision": decision.decision,
            "decision_source": decision.source,
            "conclusion": decision.conclusion,
            "reason": decision.reason,
            "confidence": decision.confidence,
            "recommended_action": decision.recommended_action,
            "reevaluate_after": decision.reevaluate_after,
            "facts": facts,
        }

        if epistemic_status is not None:
            payload["epistemic_status"] = epistemic_status

        if diagnostic_level is not None:
            payload["diagnostic_level"] = diagnostic_level

            if diagnostic_level == "CONFIRMED":
                payload["confirmation_gap"] = []

        if basis_observed_at is not None:
            payload["basis_observed_at"] = basis_observed_at

        if extra:
            payload.update(extra)

        basis_fingerprint = incident_basis_fingerprint(incident)

        if basis_fingerprint is not None:
            payload["basis_fingerprint"] = basis_fingerprint

        self.incidents.append_record(
            incident_id,
            {
                "kind": "diagnostic",
                "summary": decision.conclusion,
                "payload": payload,
            },
        )

    def _record_deterministic(
        self,
        outcome: TsunadeExpertiseOutcome,
        failures: list[InvestigationResult],
    ) -> None:
        self.incidents.append_record(
            outcome.incident_id,
            {
                "kind": "diagnostic",
                "summary": outcome.diagnosis,
                "payload": {
                    "cycle_status": "deterministic",
                    "epistemic_status": "confirmed_by_probe",
                    "diagnostic_level": "CONFIRMED",
                    "confirmation_gap": [],
                    "facts": outcome.facts,
                    "failed_investigations": [result.operation for result in failures],
                    "decision": outcome.decision or "action_required",
                    "decision_source": outcome.decision_source or "deterministic",
                    "conclusion": outcome.diagnosis,
                    "confidence": outcome.confidence or 1.0,
                    "recommended_action": (
                        outcome.proposals[0]
                        if outcome.proposals
                        else "Une intervention doit être étudiée."
                    ),
                    "reevaluate_after": None,
                },
            },
        )
        self.incidents.append_record(
            outcome.incident_id,
            {
                "kind": "action",
                "summary": (
                    "Tsunade a préparé une proposition ; "
                    "aucune action n’a été autorisée."
                ),
                "payload": {
                    "status": "proposed",
                    "authorized": False,
                    "origin": "deterministic_procedure",
                    "proposals": outcome.proposals,
                },
            },
        )

    @staticmethod
    def _known_procedure(incident: TsunadeIncident) -> KnownProcedure | None:
        identity = " ".join(
            (incident.service_id, incident.capability_id, incident.message)
        ).casefold()
        return next(
            (
                procedure
                for procedure in KNOWN_PROCEDURES
                if any(term in identity for term in procedure.matches)
            ),
            None,
        )

    @staticmethod
    def _operation_timeout(operation: str) -> int:
        return {
            "mqtt.status": 20,
            "network.ping": 15,
            "dns.query": 15,
            "dhcp.status": 15,
        }.get(operation, 5)

    @staticmethod
    def _experience_proposals(experiences: list[TsunadeExperience]) -> list[str]:
        return [
            "Réparation connue validée : "
            f"{experience.action.get('operation')} sur "
            f"{experience.action.get('target')} "
            f"({experience.success_count} réussite(s), "
            f"{experience.failure_count} échec(s))."
            for experience in experiences[:5]
        ]

    @staticmethod
    def _facts(
        incident: TsunadeIncident,
        results: list[InvestigationResult],
        log_result: dict[str, Any] | None,
    ) -> list[str]:
        facts = [
            f"Shikamaru a observé l’état {incident.severity} : {incident.message}",
            f"Nombre d’occurrences : {incident.occurrence_count}",
            f"Nombre de récurrences : {incident.recurrence_count}",
        ]
        facts.extend(investigation_summary(result) for result in results)
        findings = TsunadeExpertiseService._compact_logs(log_result or incident.context)
        facts.extend(
            f"{finding.get('source', incident.node_id)}: "
            f"{finding.get('signature', 'anomalie regroupée')} "
            f"({finding.get('occurrences', 0)} occurrence(s))"
            for finding in findings[:16]
        )
        return facts[:32]

    @staticmethod
    def _compact_logs(payload: dict[str, Any]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        sources = payload.get("sources", []) if isinstance(payload, dict) else []
        if isinstance(payload, dict) and isinstance(payload.get("findings"), list):
            sources = [payload]
        for source in sources if isinstance(sources, list) else []:
            if not isinstance(source, dict):
                continue
            for finding in source.get("findings", [])[:64]:
                if isinstance(finding, dict):
                    findings.append(
                        {
                            key: finding.get(key)
                            for key in (
                                "source",
                                "signature",
                                "category",
                                "severity",
                                "summary",
                                "occurrences",
                                "reference_occurrences",
                                "first_at",
                                "last_at",
                                "trend",
                                "references",
                            )
                        }
                    )
        # Routing sees all bounded findings; ensure the AI excerpt retains the
        # critical/new evidence that justified that routing, even late in input.
        findings.sort(
            key=lambda finding: (
                {"critical": 0, "error": 1, "warning": 2}.get(
                    finding.get("severity"), 3
                ),
                {
                    "new": 0,
                    "increasing": 1,
                    "known": 2,
                    "stable": 3,
                    "decreasing": 4,
                    "disappeared": 5,
                }.get(finding.get("trend"), 6),
            )
        )
        return findings[:32]

    @staticmethod
    def _compact_correlations(payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []

        correlations = payload.get("correlations", [])
        if not isinstance(correlations, list):
            return []

        return [
            {
                key: correlation.get(key)
                for key in (
                    "sources",
                    "occurred_at",
                    "summary",
                )
            }
            for correlation in correlations[:32]
            if isinstance(correlation, dict)
        ]

    @staticmethod
    def _bounded_json(value: object) -> str:
        def encode(item: object) -> str:
            return json.dumps(
                item,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            )

        document = redact_sensitive_value(value)

        if len(encode(document)) <= 8_000:
            return encode(document)

        if not isinstance(document, dict):
            document = {"items": document}

        document["_evidence_truncated"] = True

        # Remove whole list entries first, retaining collection flags/counts and
        # valid JSON. Last-resort string shortening is also explicitly signalled.
        while len(encode(document)) > 8_000:
            lists = []
            strings = []

            def candidates(
                item: object,
                lists: list,
                strings: list,
            ) -> None:
                if isinstance(item, dict):
                    for key, child in item.items():
                        if isinstance(child, str):
                            strings.append(
                                (
                                    len(child),
                                    item,
                                    key,
                                )
                            )
                        else:
                            candidates(
                                child,
                                lists,
                                strings,
                            )

                elif isinstance(item, list):
                    if item:
                        lists.append(
                            (
                                len(encode(item)),
                                item,
                            )
                        )

                    for child in item:
                        candidates(
                            child,
                            lists,
                            strings,
                        )

            candidates(
                document,
                lists,
                strings,
            )

            if lists:
                max(
                    lists,
                    key=lambda entry: entry[0],
                )[1].pop()

            elif strings and max(item[0] for item in strings) > 32:
                size, parent, key = max(
                    strings,
                    key=lambda entry: entry[0],
                )

                parent[key] = parent[key][: size // 2] + "…"

            else:
                return encode(
                    {
                        "_evidence_truncated": True,
                        "status": "evidence_too_large",
                    }
                )

        return encode(document)
