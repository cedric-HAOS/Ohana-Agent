"""Bounded Tsunade diagnostic cycle with optional Katsuyu AI escalation."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock, Thread
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field

from administration.incidents import (
    TsunadeExperience,
    TsunadeIncident,
    TsunadeIncidentRepository,
)
from administration.investigations import InvestigationExecutor, InvestigationResult
from administration.models import (
    AdministrationModel,
    AiInferenceParameters,
    AiInferenceResult,
)

LOGGER = logging.getLogger(__name__)


class TsunadeExpertiseConflictError(RuntimeError):
    """Raised when an incident already has an expertise cycle in progress."""


@dataclass(frozen=True, slots=True)
class KnownProcedure:
    """One explicit diagnosis procedure, never a generic executable workflow."""

    matches: tuple[str, ...]
    operations: tuple[str, ...]
    diagnosis: str
    proposals: tuple[str, ...]


KNOWN_PROCEDURES = (
    KnownProcedure(
        ("dns",),
        ("dns.query", "network.ping"),
        "Le DNS configuré ou son chemin réseau échoue à une vérification déterministe.",
        ("Vérifier le résolveur configuré et sa connectivité amont.",),
    ),
    KnownProcedure(
        ("mqtt",),
        ("mqtt.status", "network.ping"),
        "Le chemin MQTT configuré échoue à une vérification déterministe.",
        ("Vérifier la disponibilité du broker, l’authentification et le réseau.",),
    ),
    KnownProcedure(
        ("memory", "swap"),
        ("memory.status",),
        "L’hôte signale une pression déterministe sur la mémoire ou le swap.",
        ("Identifier les services les plus consommateurs avant tout redémarrage.",),
    ),
    KnownProcedure(
        ("cpu", "temperature"),
        ("cpu.status",),
        "L’hôte signale une charge CPU ou une contrainte thermique déterministe.",
        (
            "Identifier la charge active et vérifier le refroidissement "
            "avant d’intervenir.",
        ),
    ),
    KnownProcedure(
        ("disk", "storage"),
        ("disk.usage",),
        "Le système de fichiers racine signale une pression de capacité déterministe.",
        ("Examiner l’usage borné et la rétention avant toute suppression.",),
    ),
    KnownProcedure(
        ("backup",),
        ("backup.status",),
        "Le moteur de sauvegarde signale un échec déterministe.",
        ("Vérifier la dernière erreur et la validation distante avant de réessayer.",),
    ),
    KnownProcedure(
        ("network", "connectivity"),
        ("network.ping",),
        "Le test de présence réseau configuré échoue.",
        ("Vérifier l’interface cible et la route sans modifier la configuration.",),
    ),
    KnownProcedure(
        ("service", "systemd"),
        ("service.status",),
        "Une unité systemd supervisée est en échec ou inactive.",
        ("Examiner son état et ses journaux bornés avant tout redémarrage.",),
    ),
)


class TsunadeExpertiseOutcome(AdministrationModel):
    """Result of one diagnostic decision point owned by Tsunade."""

    incident_id: UUID
    status: Literal["DETERMINISTIC", "AI_QUEUED", "INSUFFICIENT_CONTEXT"]
    known_procedure: bool
    diagnosis: str
    facts: list[str] = Field(default_factory=list, max_length=32)
    proposals: list[str] = Field(default_factory=list, max_length=16)
    ai_job_id: UUID | None = None


class TsunadeExpertiseService:
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
        self._lock = Lock()
        self._inflight: set[str] = set()

    def set_ai_dispatcher(
        self, dispatcher: Callable[[dict[str, Any]], object | None]
    ) -> None:
        self.ai_dispatcher = dispatcher

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
            investigation_results = self._run_investigations(incident, procedure)
            facts = self._facts(incident, investigation_results, log_result)
            failures = [
                result
                for result in investigation_results
                if self._concrete_failure(result.operation, result)
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
                )
                self._record_deterministic(outcome, failures)
                return outcome

            parameters = self._ai_parameters(
                incident,
                procedure,
                investigation_results,
                log_result,
                experiences,
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
                )
                self.incidents.append_record(
                    incident.incident_id,
                    {
                        "kind": "diagnostic",
                        "summary": outcome.diagnosis,
                        "payload": {
                            "cycle_status": "insufficient_context",
                            "facts": facts,
                            "decision": "pending",
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
            )
            self.incidents.append_record(
                incident.incident_id,
                {
                    "kind": "diagnostic",
                    "summary": outcome.diagnosis,
                    "payload": {
                        "cycle_status": "ai_queued",
                        "facts": facts,
                        "ai_job_id": str(job_id),
                        "decision": "pending",
                    },
                },
            )
            return outcome
        finally:
            with self._lock:
                self._inflight.discard(key)

    def record_ai_result(
        self,
        incident_id: UUID | str,
        job_id: UUID | str,
        payload: dict[str, Any],
    ) -> None:
        """Persist hypotheses as proposals; never promote them to facts or results."""
        result = AiInferenceResult.model_validate(payload)
        hypotheses = [
            hypothesis.model_dump(mode="json") for hypothesis in result.hypotheses
        ]
        self.incidents.append_record(
            incident_id,
            {
                "kind": "diagnostic",
                "summary": (
                    f"Katsuyu AI propose {len(hypotheses)} hypothèse(s) ; "
                    "la décision de Tsunade reste en attente."
                ),
                "payload": {
                    "cycle_status": "ai_completed",
                    "origin": "katsuyu_ai",
                    "epistemic_status": "hypothesis",
                    "decision": "pending",
                    "job_id": str(job_id),
                    "analysis_version": result.analysis_version,
                    "verdict": result.verdict,
                    "interpretation": result.interpretation,
                    "summary": result.summary,
                    "findings": [
                        finding.model_dump(mode="json") for finding in result.findings
                    ],
                    "hypotheses": hypotheses,
                    "missing_context": result.missing_context,
                    "metrics": result.metrics.model_dump(mode="json"),
                },
            },
        )
        if result.recommended_investigation:
            self.incidents.append_record(
                incident_id,
                {
                    "kind": "action",
                    "summary": "Katsuyu AI suggère des investigations complémentaires.",
                    "payload": {
                        "status": "proposed",
                        "authorized": False,
                        "origin": "katsuyu_ai",
                        "proposals": result.recommended_investigation,
                    },
                },
            )

    def record_ai_failure(
        self,
        incident_id: UUID | str,
        job_id: UUID | str,
        error: object,
    ) -> None:
        """Keep a failed optional inference retryable and non-authoritative."""
        self.incidents.append_record(
            incident_id,
            {
                "kind": "diagnostic",
                "summary": (
                    "L’analyse Katsuyu AI facultative a échoué ; "
                    "aucune décision n’a été prise."
                ),
                "payload": {
                    "cycle_status": "ai_failed",
                    "origin": "katsuyu_ai",
                    "epistemic_status": "none",
                    "decision": "pending",
                    "job_id": str(job_id),
                    "error": str(error)[:1_000],
                },
            },
        )

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
                    "summary": f"{result.operation}: {result.status}",
                    "payload": result.model_dump(mode="json"),
                },
            )
        return results

    def _ai_parameters(
        self,
        incident: TsunadeIncident,
        procedure: KnownProcedure | None,
        results: list[InvestigationResult],
        log_result: dict[str, Any] | None,
        experiences: list[TsunadeExperience],
    ) -> dict[str, Any]:
        evidence: list[dict[str, str]] = [
            {
                "source": "architecture.concerned",
                "content": self._bounded_json(
                    {
                        "equipment": incident.equipment_id,
                        "node": incident.node_id,
                        "service": incident.service_id,
                        "capability": incident.capability_id,
                    }
                ),
            },
            {
                "source": "shikamaru.observation",
                "content": self._bounded_json(
                    {
                        "severity": incident.severity,
                        "message": incident.message,
                        "started_at": incident.started_at,
                        "last_observed_at": incident.last_observed_at,
                        "occurrences": incident.occurrence_count,
                    }
                ),
            },
            {
                "source": "history.relevant",
                "content": self._bounded_json(
                    {
                        "recurrences": incident.recurrence_count,
                        "prior_occurrences": max(0, incident.occurrence_count - 1),
                    }
                ),
            },
        ]
        if results:
            evidence.append(
                {
                    "source": "investigations.deterministic",
                    "content": self._bounded_json(
                        [result.model_dump(mode="json") for result in results]
                    ),
                }
            )
        compact_logs = self._compact_logs(log_result or incident.context)
        if compact_logs:
            evidence.append(
                {
                    "source": "logs.anomalies",
                    "content": self._bounded_json(compact_logs),
                }
            )
        if procedure is not None:
            evidence.append(
                {
                    "source": "repairs.known",
                    "content": self._bounded_json(list(procedure.proposals)),
                }
            )
        if experiences:
            evidence.append(
                {
                    "source": "repairs.validated_by_user",
                    "content": self._bounded_json(
                        [
                            {
                                "diagnostic": experience.validated_diagnostic,
                                "action": experience.action,
                                "result": experience.result,
                                "successes": experience.success_count,
                                "failures": experience.failure_count,
                                "confidence": experience.confidence,
                            }
                            for experience in experiences
                        ]
                    ),
                }
            )
        request = AiInferenceParameters(
            incident_id=incident.incident_id,
            question=(
                "Explique uniquement ce que démontrent les éléments bornés. Présente "
                "les causes incertaines comme des hypothèses avec leurs éléments "
                "concordants et contradictoires. Propose des investigations, sans "
                "décider ni autoriser une action. Réponds intégralement en français."
            ),
            evidence=evidence[:8],
            max_output_tokens=1_024,
        )
        return {
            "protocol_version": 1,
            "job_id": str(uuid4()),
            "type": "ai.inference",
            "created_at": datetime.now(UTC).isoformat(),
            "parameters": request.model_dump(mode="json"),
            "timeout": 900,
        }

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
                    "facts": outcome.facts,
                    "failed_investigations": [result.operation for result in failures],
                    "decision": "pending",
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
        return {"mqtt.status": 20, "network.ping": 15, "dns.query": 15}.get(
            operation, 5
        )

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
    def _concrete_failure(operation: str, result: InvestigationResult) -> bool:
        if result.status in {"KO", "TIMEOUT"}:
            return True
        data = result.result
        if data.get("success") is False or data.get("enabled") is False:
            return True
        status = str(data.get("status", "")).casefold()
        if status in {"ko", "error", "failed", "unhealthy", "degraded", "offline"}:
            return True
        if operation == "memory.status":
            return (
                float(data.get("memory_percent") or 0) >= 90
                or float(data.get("swap_percent") or 0) >= 75
            )
        if operation == "cpu.status":
            return (
                float(data.get("cpu_percent") or 0) >= 95
                or float(data.get("temperature_c") or 0) >= 80
            )
        if operation == "disk.usage":
            return float(data.get("disk_percent") or 0) >= 90
        if operation == "service.status":
            return bool(
                data.get("failed_systemd_units") or data.get("inactive_systemd_units")
            )
        return False

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
        facts.extend(f"{result.operation}: {result.status}" for result in results)
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
            for finding in source.get("findings", [])[:16]:
                if isinstance(finding, dict):
                    findings.append(
                        {
                            key: finding.get(key)
                            for key in (
                                "source",
                                "signature",
                                "category",
                                "severity",
                                "occurrences",
                                "first_at",
                                "last_at",
                                "trend",
                            )
                        }
                    )
        return findings[:32]

    @staticmethod
    def _bounded_json(value: object) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        return encoded[:8_000]
