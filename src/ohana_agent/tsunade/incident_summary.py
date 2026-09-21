"""One presentation contract for Vision and the bounded Shizune companion."""

import json
from datetime import datetime
from typing import Any

from ohana_agent.tsunade.diagnostic_wording import ai_conclusion
from ohana_agent.tsunade.evidence_privacy import redact_session_paths
from ohana_agent.tsunade.incidents import TsunadeIncident


def followup_covers_observation(incident: TsunadeIncident) -> bool:
    """Use persisted review provenance, including after a later redundant diagnosis."""
    review = (incident.followup or {}).get("review") or {}
    for item in review.get("parameters", {}).get("evidence", []):
        if item.get("source") != "shikamaru.observation":
            continue
        try:
            basis = json.loads(item["content"])["last_observed_at"]
            return datetime.fromisoformat(basis) >= incident.last_observed_at
        except (KeyError, TypeError, ValueError):
            return False
    return False


def incident_assessment(incident: TsunadeIncident) -> dict[str, Any]:
    """Separate observed severity, decision freshness and required operator work."""
    decision = incident.latest_decision or {}
    followup = incident.followup or {}
    followup_status = followup.get("status")
    decided_at = decision.get("occurred_at")
    try:
        basis = decision.get("basis_observed_at") or decided_at
        current = datetime.fromisoformat(str(basis)) >= incident.last_observed_at
    except (ValueError, TypeError):
        current = False
    try:
        failed_at = datetime.fromisoformat(str(followup.get("failed_at")))
        failure_current = (
            followup_status == "failed"
            and failed_at >= incident.last_observed_at
            and (not decided_at or failed_at >= datetime.fromisoformat(str(decided_at)))
        )
    except (ValueError, TypeError):
        failure_current = False
    if incident.state == "resolved":
        state, label, action = "resolved", "Résolu", None
    elif followup_status == "pending":
        state, label, action = (
            "awaiting_authorization",
            "Collecte à autoriser",
            "decisions",
        )
    elif followup_status in {"authorized", "queued", "reviewing"}:
        state, label, action = (
            "analyzing",
            "Réévaluation Katsuyu en cours ou en attente"
            if followup_status == "reviewing"
            else "Collecte Katsuyu en cours ou en attente",
            None,
        )
    elif incident.expertise_state == "ai_queued":
        state, label, action = (
            "analyzing",
            "Analyse Katsuyu en cours ou en attente",
            None,
        )
    elif failure_current:
        state, label, action = "incomplete", "Investigation interrompue", "details"
    elif (
        followup_status in {"completed", "incomplete"}
        and followup_covers_observation(incident)
        and (
            decision.get("decision") in {"investigate", "pending"}
            or decision.get("verdict") == "INSUFFICIENT_CONTEXT"
        )
    ):
        state, label, action = (
            "investigation_exhausted",
            "Investigation terminée — suite à préciser",
            "details",
        )
    elif (
        incident.expertise_state == "insufficient_context"
        or decision.get("verdict") == "INSUFFICIENT_CONTEXT"
    ):
        state, label, action = "incomplete", "Analyse incomplète", "diagnose"
    elif not decision or decision.get("decision") == "pending":
        state, label, action = "needs_diagnosis", "Diagnostic à lancer", "diagnose"
    elif not current:
        state, label, action = "stale", "Analyse à actualiser", "diagnose"
    elif decision.get("decision") == "action_required":
        state, label, action = "action_required", "Intervention à étudier", "details"
    elif decision.get("decision") == "investigate":
        state, label, action = "investigate", "À approfondir", "details"
    else:
        state, label, action = "watch", "Sous surveillance", "details"
    priority = {
        "needs_diagnosis": 1,
        "incomplete": 2,
        "stale": 3,
        "action_required": 1,
        "awaiting_authorization": 1,
        "investigate": 4,
        "investigation_exhausted": 2,
        "analyzing": 5,
        "watch": 6,
        "resolved": 7,
    }[state]
    if incident.severity == "critical" and state not in {
        "watch",
        "resolved",
        "analyzing",
    }:
        priority = 0
    if incident.capability_id == "network.reachable":
        title = f"{incident.equipment_id.upper()} est signalé absent du réseau"
    elif incident.capability_id == "logs.health":
        title = f"Journaux de {incident.equipment_id.upper()}"
    else:
        title = incident.message
    conclusion = decision.get("conclusion") or decision.get("summary")
    hypothesis = None
    if state != "resolved" and (
        decision.get("origin") == "katsuyu_ai"
        or decision.get("decision_source") == "katsuyu_ai"
    ):
        conclusion = ai_conclusion(decision.get("verdict")) or conclusion
        hypothesis = decision.get("interpretation") or decision.get("summary")
        if isinstance(hypothesis, str):
            hypothesis = redact_session_paths(hypothesis)
    return {
        "state": state,
        "label": label,
        "priority": priority,
        "title": title,
        "next_action": action,
        "decision_current": current,
        "decision": decision.get("decision"),
        "decided_at": decided_at,
        "conclusion": conclusion,
        "hypothesis": hypothesis,
        "reason": decision.get("reason"),
        "confidence": decision.get("confidence"),
        "recommended_action": (
            "Examiner l’échec et la disponibilité de Katsuyu avant de demander "
            "une nouvelle investigation."
            if failure_current and state == "incomplete"
            else decision.get("recommended_action")
        ),
        "observed_at": incident.last_observed_at.isoformat(),
        "finding_count": len(incident.context.get("findings", []))
        if incident.capability_id == "logs.health"
        else None,
        "followup": {
            "status": followup_status,
            "failed_at": followup.get("failed_at"),
            "detail": (
                "L’investigation et sa réévaluation sont terminées. "
                "La cause reste à confirmer. Aucune nouvelle collecte n’est "
                "en attente : les mêmes éléments ne déclenchent pas un nouveau "
                "cycle. Les tests supplémentaires qui restent hors du périmètre "
                "disponible doivent être précisés avant exécution."
                if state == "investigation_exhausted"
                else followup.get("detail")
            ),
            "request_id": followup.get("request_id"),
        }
        if followup
        else None,
    }
