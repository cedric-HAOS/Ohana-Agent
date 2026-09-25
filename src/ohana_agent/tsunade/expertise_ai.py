"""Katsuyu AI escalation: prompts, results, failures and follow-up reviews."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from ohana_agent.contracts.administration import (
    AiInferenceParameters,
    AiInferenceResult,
)
from ohana_agent.tsunade.diagnostic_wording import ai_conclusion
from ohana_agent.tsunade.evidence_privacy import (
    redact_sensitive_text,
    redact_sensitive_value,
)
from ohana_agent.tsunade.expertise_catalog import (
    HOME_ASSISTANT_ENTITY_ID,
    KnownProcedure,
    TsunadeDecisionResult,
)
from ohana_agent.tsunade.incident_models import (
    TsunadeExperience,
    TsunadeIncident,
)
from ohana_agent.tsunade.investigations import (
    InvestigationResult,
)


class TsunadeAIExpertise:
    """Katsuyu AI escalation: prompts, results, failures and follow-up reviews."""

    @staticmethod
    def _decision_from_ai_result(
        result: AiInferenceResult,
    ) -> TsunadeDecisionResult:
        hypothesis_confidence = max(
            (hypothesis.confidence for hypothesis in result.hypotheses),
            default=0.0,
        )

        if result.verdict == "OK":
            return TsunadeDecisionResult(
                decision="watch",
                source="katsuyu_ai",
                conclusion=ai_conclusion("OK"),
                reason=(
                    "Katsuyu AI n’identifie pas d’élément suffisant pour "
                    "justifier une intervention."
                ),
                confidence=min(max(hypothesis_confidence, 0.70), 0.85),
                recommended_action=("Maintenir la surveillance déterministe."),
                reevaluate_after="next_logs_health_check",
            )

        if result.verdict == "KO":
            return TsunadeDecisionResult(
                decision="investigate",
                source="katsuyu_ai",
                conclusion=ai_conclusion("KO"),
                reason=(
                    "L’analyse corrélée met en évidence des éléments qui "
                    "méritent une investigation, sans autoriser de correction."
                ),
                confidence=min(max(hypothesis_confidence, 0.60), 0.85),
                recommended_action=(
                    result.recommended_investigation[0]
                    if result.recommended_investigation
                    else "Approfondir les éléments identifiés par Katsuyu."
                ),
                reevaluate_after=None,
            )

        return TsunadeDecisionResult(
            decision="watch",
            source="katsuyu_ai",
            conclusion=(
                "L’analyse Katsuyu ne dispose pas d’un contexte suffisant "
                "pour confirmer une cause."
            ),
            reason="Les éléments disponibles ne permettent pas de confirmer une cause.",
            confidence=0.60,
            recommended_action=(
                result.recommended_investigation[0]
                if result.recommended_investigation
                else "Attendre de nouveaux éléments déterministes."
            ),
            reevaluate_after="next_logs_health_check",
        )

    def record_ai_result(
        self,
        incident_id: UUID | str,
        job_id: UUID | str,
        payload: dict[str, Any],
        *,
        evidence: list[dict[str, Any]] | None = None,
    ) -> None:
        """Persist hypotheses as proposals; never promote them to facts or results."""
        if any(
            event.payload.get("job_id") == str(job_id)
            and event.payload.get("cycle_status") == "ai_completed"
            for event in self.incidents.get(incident_id).events
        ):
            return
        payload = redact_sensitive_value(payload)
        result = AiInferenceResult.model_validate(payload)
        decision = self._decision_from_ai_result(result)
        collection_facts = self._followup_collection_facts(evidence or [])
        if result.verdict == "INSUFFICIENT_CONTEXT" and collection_facts:
            truncation = (
                "Collecte tronquée."
                if collection_facts["truncated"]
                else "Collecte non tronquée."
            )
            reason = (
                f"Recherche ciblée : {collection_facts['matched_lines']} lignes "
                f"correspondantes, {collection_facts['anomaly_count']} anomalies "
                f"reconnues. {truncation} Ce résultat porte uniquement sur le "
                "filtre et la fenêtre de la collecte ; il ne suffit pas à "
                "confirmer une cause ou une résolution globale."
            )
            decision = replace(decision, reason=reason)
        hypotheses = [
            hypothesis.model_dump(mode="json") for hypothesis in result.hypotheses
        ]
        diagnostic_level = None
        confirmation_gap: list[str] = []

        if result.verdict == "KO" and hypotheses:
            diagnostic_level = "PROBABLE"

            confirmation_gap = [
                str(item) for item in result.missing_context[:16] if str(item).strip()
            ]

            if not confirmation_gap:
                confirmation_gap = [
                    (
                        "Une confirmation déterministe reste nécessaire "
                        "avant de considérer la cause comme établie."
                    )
                ]

        elif result.verdict == "INSUFFICIENT_CONTEXT":
            diagnostic_level = "INSUFFICIENT_CONTEXT"

            confirmation_gap = [
                str(item) for item in result.missing_context[:16] if str(item).strip()
            ]
        investigation_commands = self._suggested_investigation_commands(
            result,
            evidence=evidence,
        )
        basis_observed_at = None
        for item in evidence or []:
            if item.get("source") == "shikamaru.observation":
                try:
                    basis_observed_at = json.loads(item["content"]).get(
                        "last_observed_at"
                    )
                except (ValueError, TypeError, KeyError):
                    pass
        self.incidents.append_record(
            incident_id,
            {
                "kind": "diagnostic",
                "summary": (
                    f"Tsunade retient la décision « {decision.decision} » "
                    f"après l’analyse Katsuyu AI."
                ),
                "payload": {
                    "cycle_status": "ai_completed",
                    "basis_observed_at": basis_observed_at,
                    "origin": "katsuyu_ai",
                    "epistemic_status": "hypothesis",
                    "diagnostic_level": diagnostic_level,
                    "confirmation_gap": confirmation_gap,
                    "decision": decision.decision,
                    "decision_source": decision.source,
                    "conclusion": decision.conclusion,
                    "reason": decision.reason,
                    "confidence": decision.confidence,
                    "recommended_action": decision.recommended_action,
                    "reevaluate_after": decision.reevaluate_after,
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
                    "investigation_commands": investigation_commands,
                    "metrics": result.metrics.model_dump(mode="json"),
                    "collection_facts": collection_facts,
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
                        "investigation_commands": investigation_commands,
                    },
                },
            )

    def record_ai_failure(
        self,
        incident_id: UUID | str,
        job_id: UUID | str,
        error: object,
    ) -> None:
        """Fallback to a bounded Tsunade decision when optional AI fails."""
        decision = TsunadeDecisionResult(
            decision="watch",
            source="fallback",
            conclusion=(
                "L’analyse Katsuyu AI n’a pas abouti. "
                "Aucun élément ne permet d’autoriser une action corrective."
            ),
            reason=(
                "Le moteur déterministe reste la référence ; "
                "l’échec de l’analyse facultative ne bloque pas Tsunade."
            ),
            confidence=0.70,
            recommended_action=(
                "Maintenir la surveillance et réévaluer lors du prochain contrôle."
            ),
            reevaluate_after="next_logs_health_check",
        )

        safe_error = redact_sensitive_text(str(error))[:1_000]
        self.incidents.append_record(
            incident_id,
            {
                "kind": "diagnostic",
                "summary": decision.conclusion,
                "payload": {
                    "cycle_status": "ai_failed",
                    "origin": "katsuyu_ai",
                    "epistemic_status": "none",
                    "diagnostic_level": "INSUFFICIENT_CONTEXT",
                    "confirmation_gap": [
                        "L'analyse Katsuyu facultative n'a pas abouti.",
                    ],
                    "decision": decision.decision,
                    "decision_source": decision.source,
                    "conclusion": decision.conclusion,
                    "reason": decision.reason,
                    "confidence": decision.confidence,
                    "recommended_action": decision.recommended_action,
                    "reevaluate_after": decision.reevaluate_after,
                    "job_id": str(job_id),
                    "error": safe_error,
                },
            },
        )

    def _ai_parameters(
        self,
        incident: TsunadeIncident,
        procedure: KnownProcedure | None,
        results: list[InvestigationResult],
        log_result: dict[str, Any] | None,
        experiences: list[TsunadeExperience],
        *,
        supervisor_evidence: dict[str, Any] | None = None,
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
        log_payload = log_result or incident.context
        compact_logs = self._compact_logs(log_payload)
        compact_correlations = self._compact_correlations(log_payload)

        historical = log_payload.get("historical_findings", [])
        if compact_logs or compact_correlations or historical:
            evidence.append(
                {
                    "source": "logs.analysis",
                    "content": self._bounded_json(
                        {
                            "collection": {
                                key: log_payload.get(key)
                                for key in (
                                    "source",
                                    "analyzed_at",
                                    "window_started_at",
                                    "window_ended_at",
                                    "truncated",
                                    "analyzed_lines",
                                )
                            },
                            "evidence_scope": {
                                "selected_finding_count_before_encoding": len(
                                    compact_logs
                                ),
                                "total_finding_count": sum(
                                    len(s.get("findings", []))
                                    for s in (
                                        log_payload.get("sources", [])
                                        if "sources" in log_payload
                                        else [log_payload]
                                    )
                                    if isinstance(s, dict)
                                ),
                                "undated_finding_count": sum(
                                    not (f.get("first_at") and f.get("last_at"))
                                    for s in (
                                        log_payload.get("sources", [])
                                        if "sources" in log_payload
                                        else [log_payload]
                                    )
                                    if isinstance(s, dict)
                                    for f in s.get("findings", [])
                                    if isinstance(f, dict)
                                ),
                                "limit": (
                                    "Un groupe non daté ne prouve ni récence ni "
                                    "appartenance à la fenêtre. L'extrait IA peut "
                                    "omettre des groupes ; voir les compteurs "
                                    "et _evidence_truncated."
                                ),
                            },
                            "findings": compact_logs,
                            "historical_findings": historical[:16],
                            "historical_limit": (
                                "Historique conservé ; ne prouve pas "
                                "une persistance actuelle."
                            ),
                            "correlations": compact_correlations,
                            "new_anomaly_count": (
                                log_payload.get("new_anomaly_count")
                                if isinstance(log_payload, dict)
                                else None
                            ),
                            "worsening_anomaly_count": (
                                log_payload.get("worsening_anomaly_count")
                                if isinstance(log_payload, dict)
                                else None
                            ),
                            "recommended_investigations": (
                                log_payload.get("recommended_investigations", [])
                                if isinstance(log_payload, dict)
                                else []
                            ),
                        }
                    ),
                }
            )
        if supervisor_evidence is not None:
            evidence.append(
                {
                    "source": "supervisor.teleinformation",
                    "content": self._bounded_json(supervisor_evidence),
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
                " Les groupes sans date ne prouvent pas une panne actuelle. "
                "Distingue troncature de collecte et extrait IA réduit "
                "(_evidence_truncated et evidence_scope)."
            ),
            evidence=evidence[:8],
            max_output_tokens=8_192,
        )
        return {
            "protocol_version": 1,
            "job_id": str(uuid4()),
            "type": "ai.inference",
            "created_at": datetime.now(ZoneInfo("Europe/Paris")).isoformat(),
            "parameters": request.model_dump(mode="json"),
            "timeout": 900,
        }

    @staticmethod
    def _followup_collection_facts(evidence: list[dict[str, Any]]) -> dict | None:
        """Use only explicit, typed collection facts, never model prose."""
        for item in evidence:
            if item.get("source") != "investigation.followup":
                continue
            try:
                document = json.loads(item["content"])
                result = document["result"]
                matches = result["matched_lines"]
                findings = result["findings"]
                finding_count = result.get("finding_count", len(findings))
                truncated = result["truncated"]
            except (ValueError, TypeError, KeyError):
                continue
            if (
                type(matches) is not int
                or matches < 0
                or not isinstance(findings, list)
                or type(truncated) is not bool
                or type(finding_count) is not int
                or finding_count < len(findings)
            ):
                continue
            return {
                "source": "investigation.followup",
                "matched_lines": matches,
                "anomaly_count": finding_count,
                "truncated": truncated,
            }
        return None

    def prepare_followup_review(
        self, incident: TsunadeIncident, request_id: str, collection: Any
    ) -> dict[str, Any]:
        """Include search scope and limits without asserting a healthy system."""
        # Keep the original findings: a targeted search can return no anomalies
        # without explaining or invalidating the earlier observation.
        payload = self._ai_parameters(incident, None, [], incident.context, [])
        payload["parameters"]["question"] += (
            " Les preuves logs.analysis décrivent les anomalies à l'origine de "
            "l'incident, datées par shikamaru.observation ; elles ne démontrent "
            "pas leur persistance actuelle. Compare-les au résultat plus récent "
            "investigation.followup, uniquement dans sa fenêtre et son périmètre. "
            "matched_lines compte les lignes correspondant au filtre, pas les "
            "anomalies : findings vide signifie qu'aucune anomalie n'a été "
            "reconnue dans cette collecte. truncated=false signifie que la "
            "collecte n'est pas tronquée ; seule la valeur true prouve une "
            "troncature. Une fenêtre temporelle limitée n'est pas une troncature. "
            "Une anomalie sans first_at/last_at est non datée : l'heure de "
            "collecte ne prouve pas qu'elle est récente ni qu'elle appartient "
            "à la fenêtre demandée. "
            "Ne conclus ni à une panne persistante sur le seul historique, ni "
            "à une résolution globale sur cette seule recherche ciblée."
            " _evidence_truncated indique un extrait de preuve abrégé pour l’IA, "
            "distinct de la troncature de collecte. finding_count garde le nombre "
            "de groupes avant réduction de cet extrait."
        )
        payload["parameters"]["evidence"].append(
            {
                "source": "investigation.followup",
                "content": self._bounded_json(
                    {
                        "request_id": request_id,
                        "collection_job_id": str(collection.job_id),
                        "scope": collection.parameters,
                        "result": {
                            **collection.result,
                            "finding_count": len(collection.result.get("findings", [])),
                        },
                        "limit": (
                            "Aucune correspondance ne prouve pas la résolution. "
                            "Cette réévaluation termine le cycle de collecte autorisé."
                        ),
                    }
                ),
            }
        )
        # Validate the combined budget before persisting the execution intent.
        AiInferenceParameters.model_validate(payload["parameters"])
        return payload

    @staticmethod
    def _suggested_investigation_commands(
        result: AiInferenceResult,
        *,
        evidence: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        text = " ".join(
            [
                result.summary,
                result.interpretation,
                *result.recommended_investigation,
                *(hypothesis.statement for hypothesis in result.hypotheses),
                *(
                    evidence
                    for hypothesis in result.hypotheses
                    for evidence in hypothesis.supporting_evidence
                ),
                *(
                    str(item.get("content", ""))
                    for item in (evidence or [])
                    if isinstance(item, dict)
                ),
            ]
        )
        normalized_text = text.casefold()

        commands: list[dict[str, str]] = []
        entity_ids = list(
            dict.fromkeys(
                entity_id.casefold()
                for entity_id in HOME_ASSISTANT_ENTITY_ID.findall(text)
                if entity_id.casefold().startswith("sensor.")
            )
        )[:16]
        if "template" in normalized_text and "float" in normalized_text and entity_ids:
            quoted_entity_ids = ", ".join(repr(entity_id) for entity_id in entity_ids)
            commands.append(
                {
                    "title": "Vérifier les entités citées par le journal",
                    "target": "Home Assistant > Outils de développement > Modèle",
                    "safety": "Lecture seule",
                    "command": "\n".join(
                        [
                            f"{{% set entity_ids = [{quoted_entity_ids}] %}}",
                            "{% for entity_id in entity_ids %}",
                            "{{ entity_id }} ; "
                            "{{ state_attr(entity_id, 'friendly_name') "
                            "| default(entity_id, true) }} ; "
                            "{{ states(entity_id) }}",
                            "{% endfor %}",
                        ]
                    ),
                    "expected": (
                        "Affiche toujours le nom et l’état courant de chaque entité "
                        "explicitement citée par le journal Home Assistant."
                    ),
                }
            )

        return commands[:8]
