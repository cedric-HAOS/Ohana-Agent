"""One presentation contract for Vision and the bounded Shizune companion."""

from datetime import datetime
from typing import Any

from ohana_agent.tsunade.incidents import TsunadeIncident


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
    return {
        "state": state,
        "label": label,
        "priority": priority,
        "title": title,
        "next_action": action,
        "decision_current": current,
        "decision": decision.get("decision"),
        "decided_at": decided_at,
        "conclusion": decision.get("conclusion") or decision.get("summary"),
        "reason": decision.get("reason"),
        "confidence": decision.get("confidence"),
        "recommended_action": decision.get("recommended_action"),
        "observed_at": incident.last_observed_at.isoformat(),
        "finding_count": len(incident.context.get("findings", []))
        if incident.capability_id == "logs.health"
        else None,
        "followup": {
            "status": followup_status,
            "detail": followup.get("detail"),
            "request_id": followup.get("request_id"),
        }
        if followup
        else None,
    }
