"""Phase 3 hardening: a finer, explained comparison between two incidents.

Equipment and capability were the only criteria. Two host.health incidents
of INFRA-01 can have nothing in common (a stopped Vision, a full disk): the
comparison also looks at the reasons, the message once numbers are removed,
the service and the log anomalies. Each criterion present on either side
weighs in; the result lists what matched and what differs.

Closeness in time is never a criterion, and a similarity is never a cause.
"""

from __future__ import annotations

import re
from typing import Any

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_SPACES = re.compile(r"\s+")
WEIGHTS = {
    "equipment": 0.25,
    "service": 0.15,
    "reasons": 0.3,
    "message": 0.15,
    "logs": 0.15,
}
SIMILAR_THRESHOLD = 0.5


def fingerprint(
    *,
    equipment_id: str,
    capability_id: str,
    service_id: str | None,
    message: str,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    context = context if isinstance(context, dict) else {}
    reasons: set[str] = set()
    for holder in (context, context.get("host_health")):
        if isinstance(holder, dict) and isinstance(holder.get("reasons"), list):
            reasons.update(str(reason) for reason in holder["reasons"])
    logs: set[str] = set()
    for key in ("findings", "background_findings", "log_findings", "anomalies"):
        values = context.get(key)
        if isinstance(values, list):
            logs.update(
                str(item["signature"])
                for item in values
                if isinstance(item, dict) and item.get("signature")
            )
    normalized = _SPACES.sub(" ", _NUMBER.sub("#", str(message or "").lower()))
    return {
        "equipment_id": equipment_id,
        "capability_id": capability_id,
        "service_id": service_id,
        "reasons": sorted(reasons),
        "message": normalized.strip()[:160],
        "logs": sorted(logs),
    }


def _jaccard(left: list[str], right: list[str]) -> float:
    union = set(left) | set(right)
    return len(set(left) & set(right)) / len(union) if union else 0.0


def compare(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Score in [0, 1] with the criteria that matched and the differences."""
    if left["capability_id"] != right["capability_id"]:
        return {
            "score": 0.0,
            "matched": [],
            "differences": ["Capacité différente"],
            "different_nature": True,
        }
    parts: list[tuple[float, float]] = []
    matched: list[str] = []
    differences: list[str] = []

    same_equipment = left["equipment_id"] == right["equipment_id"]
    parts.append((WEIGHTS["equipment"], 1.0 if same_equipment else 0.0))
    (matched if same_equipment else differences).append(
        "Même équipement" if same_equipment else "Autre équipement"
    )
    if left["service_id"] or right["service_id"]:
        same_service = left["service_id"] == right["service_id"]
        parts.append((WEIGHTS["service"], 1.0 if same_service else 0.0))
        if same_service:
            matched.append("Même service")
    different_nature = False
    if left["reasons"] or right["reasons"]:
        overlap = _jaccard(left["reasons"], right["reasons"])
        parts.append((WEIGHTS["reasons"], overlap))
        common = sorted(set(left["reasons"]) & set(right["reasons"]))
        if common:
            matched.append("Mêmes raisons : " + ", ".join(common))
        if set(left["reasons"]) != set(right["reasons"]):
            differences.append(
                "Raisons : "
                + (", ".join(left["reasons"]) or "aucune")
                + " / "
                + (", ".join(right["reasons"]) or "aucune")
            )
        # Both explain the failure and share nothing: another failure mode.
        different_nature = bool(left["reasons"] and right["reasons"] and not common)
    if left["message"] or right["message"]:
        same_message = left["message"] == right["message"]
        parts.append((WEIGHTS["message"], 1.0 if same_message else 0.0))
        if same_message:
            matched.append("Même message")
    if left["logs"] or right["logs"]:
        overlap = _jaccard(left["logs"], right["logs"])
        parts.append((WEIGHTS["logs"], overlap))
        common_logs = set(left["logs"]) & set(right["logs"])
        if common_logs:
            matched.append(f"{len(common_logs)} anomalie(s) de journaux communes")
    total = sum(weight for weight, _ in parts)
    score = sum(weight * value for weight, value in parts) / total if total else 0.0
    return {
        "score": round(score, 2),
        "matched": matched,
        "differences": differences,
        "different_nature": different_nature,
    }
