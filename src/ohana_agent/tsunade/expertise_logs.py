"""Tsunade review of Katsuyu log health findings."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from ohana_agent.tsunade.evidence_privacy import (
    redact_sensitive_text,
)
from ohana_agent.tsunade.expertise_catalog import (
    TsunadeDecisionResult,
    TsunadeExpertiseConflictError,
)
from ohana_agent.tsunade.incident_models import (
    TsunadeIncident,
)


class TsunadeLogExpertise:
    """Tsunade review of Katsuyu log health findings."""

    def review_log_health(
        self, incident_id: UUID | str, job_id: UUID | str, result: dict[str, Any]
    ) -> None:
        """Review each source once per collection, synchronously before idle polling."""
        incident = self.incidents.get(incident_id)
        if incident.state != "active" or any(
            event.payload.get("review_job_id") == str(job_id)
            for event in incident.events
        ):
            return
        if result.get("sources") and incident.capability_id == "logs.health":
            if str(incident.last_observation_id) != str(job_id):
                # A newer global collection has already replaced this evidence.
                if any(
                    event.payload.get("job_id") == str(job_id)
                    and "result" in event.payload
                    for event in incident.events
                ):
                    return
        if incident.expertise_state == "ai_queued":
            # The existing bounded AI job retains the worker; do not duplicate it.
            raise TsunadeExpertiseConflictError("An AI analysis is already pending")
        sources = result.get("sources", [])
        source = next(
            (item for item in sources if item.get("source") == incident.equipment_id),
            None,
        )
        if source is None:
            return
        evidence = {
            **source,
            **{
                key: result.get(key)
                for key in ("analyzed_at", "window_started_at", "window_ended_at")
            },
            "correlations": [
                item
                for item in result.get("correlations", [])
                if incident.equipment_id in item.get("sources", [])
            ],
        }
        reviewed = {
            fingerprint
            for event in incident.events
            for fingerprint in event.payload.get("reviewed_correlations", [])
        }
        fingerprints = []
        new_correlations = []
        for correlation in self._compact_correlations(evidence):
            canonical = {
                **correlation,
                "sources": sorted(correlation.get("sources") or []),
            }
            fingerprint = hashlib.sha256(
                json.dumps(canonical, sort_keys=True, default=str).encode()
            ).hexdigest()
            fingerprints.append(fingerprint)
            if fingerprint not in reviewed:
                new_correlations.append(correlation)
        evidence["new_correlations"] = new_correlations
        evidence["reviewed_log_findings"] = self._reviewed_log_findings(incident)
        outcome = self.diagnose(incident_id, log_result=evidence)
        if outcome is not None and outcome.status == "INSUFFICIENT_CONTEXT":
            # No AI job was dispatched: keep correlations eligible for a later
            # collection when the optional analysis path becomes available.
            fingerprints = []
        self.incidents.append_record(
            incident_id,
            {
                "kind": "investigation",
                "summary": "Tsunade a réévalué le dernier contrôle des journaux.",
                "payload": {
                    "review_job_id": str(job_id),
                    "reviewed_correlations": fingerprints,
                    "reviewed_log_findings": [
                        fingerprint
                        for finding in source.get("findings", [])[:64]
                        if (fingerprint := self._log_finding_fingerprint(finding))
                        and (
                            outcome is not None
                            and outcome.status == "AI_QUEUED"
                            or fingerprint in evidence["reviewed_log_findings"]
                        )
                    ],
                },
            },
        )

    @staticmethod
    def _log_finding_fingerprint(finding: dict[str, Any]) -> str | None:
        """Identify observed evidence, independently of baseline and wording."""
        if not isinstance(finding, dict):
            return None
        signature = finding.get("signature")
        if not isinstance(signature, str) or not signature:
            return None
        last_at = finding.get("last_at")
        if isinstance(last_at, str):
            try:
                parsed = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
                if parsed.utcoffset() is not None:
                    last_at = parsed.astimezone(ZoneInfo("UTC")).isoformat()
            except ValueError:
                pass
        canonical = {
            "signature": redact_sensitive_text(signature),
            "severity": finding.get("severity"),
            "category": finding.get("category"),
            "occurrences": finding.get("occurrences"),
            "last_at": last_at,
        }
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True, default=str).encode()
        ).hexdigest()

    def _reviewed_log_findings(self, incident: TsunadeIncident) -> list[str]:
        reviewed = self.incidents.reviewed_log_findings(incident.incident_id)
        collection: dict[str, Any] = {}
        collection_job = None
        submitted = False
        # Also recognize pre-upgrade reviews, without rewriting their history.
        for event in sorted(incident.events, key=lambda item: item.event_id):
            payload = event.payload
            source = payload.get("result")
            if (
                isinstance(source, dict)
                and source.get("source") == incident.equipment_id
                and "analyzed_lines" in source
            ):
                collection = source
                collection_job = payload.get("job_id")
                submitted = False
            if (
                payload.get("cycle_status") == "ai_queued"
                and payload.get("trigger") == "automatic_escalation"
                and payload.get("ai_job_id")
            ):
                submitted = True
            if "reviewed_log_findings" in payload:
                reviewed.update(payload["reviewed_log_findings"])
            elif (
                submitted
                and collection_job
                and payload.get("review_job_id") == collection_job
            ):
                reviewed.update(
                    fingerprint
                    for finding in collection.get("findings", [])[:64]
                    if (fingerprint := self._log_finding_fingerprint(finding))
                )
        return sorted(reviewed)

    @classmethod
    def _log_decision(
        cls,
        incident: TsunadeIncident,
        log_result: dict[str, Any] | None,
    ) -> TsunadeDecisionResult:
        payload = log_result or incident.context
        # Routing uses every bounded finding, not the shorter AI excerpt.
        sources = payload.get("sources", [])
        if isinstance(payload.get("findings"), list):
            sources = [payload]
        findings = [
            finding
            for source in sources[:4]
            if isinstance(source, dict)
            for finding in source.get("findings", [])[:64]
            if isinstance(finding, dict)
        ]
        correlations = (
            payload["new_correlations"]
            if "new_correlations" in payload
            else cls._compact_correlations(payload)
        )

        if not findings:
            return TsunadeDecisionResult(
                decision="watch",
                source="deterministic",
                conclusion=(
                    "Aucune anomalie exploitable n’a été "
                    "isolée dans les éléments "
                    "actuellement disponibles."
                ),
                reason=(
                    "La collecte est tronquée : l’absence de finding ne prouve "
                    "pas la disparition des anomalies."
                    if any(
                        s.get("truncated") is True
                        for s in sources
                        if isinstance(s, dict)
                    )
                    else "Le contexte est trop limité pour justifier une investigation."
                ),
                confidence=0.75,
                recommended_action="Surveiller le prochain contrôle des journaux.",
                reevaluate_after="next_logs_health_check",
            )

        meaningful_changes: list[dict[str, Any]] = []
        warning_changes: list[dict[str, Any]] = []
        critical_findings: list[dict[str, Any]] = []
        reviewed = set(payload.get("reviewed_log_findings", []))
        already_reviewed = 0

        for finding in findings:
            occurrences = int(finding.get("occurrences") or 0)
            reference = finding.get("reference_occurrences")
            trend = str(finding.get("trend") or "")
            severity = str(finding.get("severity") or "")

            relative_change = 0.0
            if isinstance(reference, int) and reference > 0:
                relative_change = (occurrences - reference) / reference
            elif reference == 0 and occurrences > 0:
                relative_change = 1.0

            if cls._log_finding_fingerprint(finding) in reviewed:
                already_reviewed += int(
                    severity == "critical"
                    or trend in {"new", "increasing"}
                    or relative_change >= 0.25
                )
                continue

            if severity == "critical" and trend not in {
                "decreasing",
                "disappeared",
            }:
                critical_findings.append(finding)

            if trend in {"new", "increasing"} or relative_change >= 0.50:
                meaningful_changes.append(finding)
            elif relative_change >= 0.25:
                warning_changes.append(finding)

        if correlations or critical_findings or len(meaningful_changes) >= 2:
            reasons: list[str] = []

            if correlations:
                reasons.append(
                    f"{len(correlations)} corrélation(s) temporelle(s) détectée(s)"
                )

            if critical_findings:
                reasons.append(f"{len(critical_findings)} anomalie(s) critique(s)")

            if len(meaningful_changes) >= 2:
                reasons.append(
                    f"{len(meaningful_changes)} anomalie(s) en évolution significative"
                )

            return TsunadeDecisionResult(
                decision="investigate",
                source="deterministic",
                conclusion=(
                    "Les journaux contiennent plusieurs éléments suffisamment "
                    "significatifs pour justifier une analyse approfondie."
                ),
                reason=" ; ".join(reasons),
                confidence=0.90,
                recommended_action=(
                    "Corréler les anomalies et rechercher une cause commune avant "
                    "toute action corrective."
                ),
                reevaluate_after=None,
            )

        if meaningful_changes or warning_changes:
            return TsunadeDecisionResult(
                decision="watch",
                source="deterministic",
                conclusion=(
                    "Une évolution est visible, mais elle ne démontre pas encore "
                    "une dégradation nécessitant une intervention."
                ),
                reason=(
                    f"{len(meaningful_changes) + len(warning_changes)} anomalie(s) "
                    "présentent une évolution à surveiller."
                ),
                confidence=0.85,
                recommended_action=(
                    "Comparer avec le prochain contrôle avant d’approfondir."
                ),
                reevaluate_after="next_logs_health_check",
            )

        if already_reviewed:
            return TsunadeDecisionResult(
                decision="watch",
                source="deterministic",
                conclusion=(
                    "Ce contrôle n’apporte pas de nouvelle preuve justifiant "
                    "une expertise automatique supplémentaire."
                ),
                reason=(
                    f"{already_reviewed} groupe(s) déjà pris en compte lors d’une "
                    "demande d’expertise. Les limites de collecte "
                    "et les hypothèses antérieures restent à vérifier."
                ),
                confidence=0.5,
                recommended_action=(
                    "Surveiller une nouvelle preuve ou demander explicitement "
                    "un diagnostic complémentaire."
                ),
                reevaluate_after="next_logs_health_check",
            )

        if any(
            source.get("truncated") is True
            for source in sources
            if isinstance(source, dict)
        ):
            return TsunadeDecisionResult(
                decision="watch",
                source="deterministic",
                conclusion=(
                    "Les éléments reçus ne montrent pas d’aggravation, "
                    "mais la collecte est tronquée."
                ),
                reason=(
                    "Les données omises empêchent de conclure à la stabilité "
                    "de l’ensemble des journaux."
                ),
                confidence=0.5,
                recommended_action=(
                    "Comparer une collecte complète ou une recherche ciblée autorisée."
                ),
                reevaluate_after="next_logs_health_check",
            )

        return TsunadeDecisionResult(
            decision="stable",
            source="deterministic",
            conclusion=(
                "Les anomalies observées sont connues et ne présentent pas "
                "d’aggravation significative."
            ),
            reason=(
                "Aucune anomalie nouvelle, forte augmentation, corrélation "
                "temporelle ou criticité supplémentaire n’a été détectée."
            ),
            confidence=0.95,
            recommended_action="Aucune investigation supplémentaire nécessaire.",
            reevaluate_after="next_logs_health_check",
        )
