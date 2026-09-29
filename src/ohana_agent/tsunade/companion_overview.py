"""The companion's reassuring half: essential services and logs by equipment."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from ohana_agent.tsunade.incident_models import TsunadeIncident
from ohana_agent.tsunade.incident_summary import incident_assessment
from ohana_agent.tsunade.local_time import paris_iso

# The services worth a tile, in display order. Only those configured show up.
SERVICE_TILES = (
    ("dns", "DNS"),
    ("dhcp", "DHCP"),
    ("mqtt", "MQTT"),
    ("home_assistant", "Home Assistant"),
    ("zwave", "Z-Wave"),
    ("teleinformation", "Téléinformation"),
)
# Sources reviewed by the daily log check, in display order.
LOG_SOURCES = ("infra-01", "linky-01", "zwave-01", "ha-01")

_SEVERITY = {"healthy": 0, "suspended": 1, "unknown": 1, "degraded": 2, "unhealthy": 3}
_STATUS = {0: "healthy", 1: "unknown", 2: "degraded", 3: "critical"}
_DETAIL = {
    "degraded": "Dégradé",
    "critical": "En panne",
    "unknown": "Pas de mesure récente",
}
_LOG_ORDER = {"decision": 0, "attention": 1, "analyzing": 2, "watch": 3, "ok": 4}


def format_latency(latency_ms: float) -> str:
    """French short duration: ``4,6 ms`` under a second, ``1,2 s`` above."""
    if latency_ms >= 1000:
        return f"{latency_ms / 1000:.1f} s".replace(".", ",")
    return f"{latency_ms:.1f} ms".replace(".", ",")


def services_overview(
    states: list[dict[str, Any]],
    service_types: Mapping[str, str],
) -> dict[str, Any]:
    """One tile per configured essential service, its worst check deciding.

    A tile with no recent measure is ``unknown``, never healthy: a stopped check
    must not read as a reassuring one. ``checked_at`` is the latest measure seen.
    """
    items: list[dict[str, Any]] = []
    latest: datetime | None = None
    for service_type, label in SERVICE_TILES:
        identifiers = sorted(
            identifier
            for identifier, kind in service_types.items()
            if kind == service_type
        )
        if not identifiers:
            continue
        rows = [state for state in states if state["service"] in identifiers]
        rows.sort(
            key=lambda state: (identifiers.index(state["service"]), state["capability"])
        )
        worst = max((_SEVERITY.get(row["status"], 1) for row in rows), default=1)
        status = _STATUS[worst]
        latency = next(
            (row["latency_ms"] for row in rows if row["latency_ms"] is not None), None
        )
        detail = (
            format_latency(latency)
            if status == "healthy" and latency is not None
            else ""
            if status == "healthy"
            else _DETAIL[status]
        )
        for row in rows:
            if latest is None or row["observed_at"] > latest:
                latest = row["observed_at"]
        items.append(
            {"id": service_type, "label": label, "status": status, "detail": detail}
        )
    return {
        "checked_at": paris_iso(latest) if latest is not None else None,
        "items": items,
    }


def _finding_detail(incident: TsunadeIncident) -> str:
    count = len(incident.context.get("findings", []))
    if count:
        return f"{count} anomalie(s) à examiner"
    return "Collecte sans résultat exploitable"


def logs_overview(
    incidents: Iterable[TsunadeIncident],
    pending_incident_ids: set[str],
    accepted_counts: Mapping[str, int],
    checked_at: datetime | None,
) -> dict[str, Any]:
    """Log review by equipment: open incident, known noise or nothing to report.

    ``checked_at`` is the date of the last completed review; the block states
    when the review ran, never a global verdict a single equipment contradicts.
    """
    active = {
        incident.equipment_id: incident
        for incident in incidents
        if incident.capability_id == "logs.health"
    }
    equipments: list[dict[str, Any]] = []
    for source in LOG_SOURCES:
        incident = active.get(source)
        entry: dict[str, Any] = {
            "equipment": source,
            "label": source.upper(),
            "incident_id": None,
        }
        if incident is not None:
            state = incident_assessment(incident)["state"]
            entry["incident_id"] = str(incident.incident_id)
            entry["detail"] = _finding_detail(incident)
            if str(incident.incident_id) in pending_incident_ids or state in {
                "awaiting_authorization",
            }:
                entry["status"] = "decision"
            elif state == "analyzing":
                entry["status"] = "analyzing"
            elif state == "watch":
                entry["status"] = "watch"
            else:
                entry["status"] = "attention"
        elif accepted_counts.get(source, 0) > 0:
            entry["status"] = "watch"
            entry["detail"] = f"Bruit connu · {accepted_counts[source]} accepté(s)"
        else:
            entry["status"] = "ok"
            entry["detail"] = "Aucune anomalie"
        equipments.append(entry)
    equipments.sort(key=lambda entry: _LOG_ORDER[entry["status"]])
    return {
        "checked_at": paris_iso(checked_at) if checked_at is not None else None,
        "equipments": equipments,
    }
