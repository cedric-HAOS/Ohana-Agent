"""Stable fingerprints for semantic diagnostic bases."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def incident_basis_fingerprint(incident: Any) -> str | None:
    """Return a stable fingerprint for one semantic diagnostic basis."""

    capability_id = str(getattr(incident, "capability_id", "") or "")

    if capability_id != "teleinformation.freshness":
        return None

    context = getattr(incident, "context", None)

    if not isinstance(context, dict):
        return None

    if context.get("mode") != "direct_http":
        return None

    payload = {
        "fault": "teleinformation_stale",
        "node_id": getattr(incident, "node_id", None),
        "service_id": getattr(incident, "service_id", None),
        "capability_id": capability_id,
        "severity": getattr(incident, "severity", None),
        "mode": context.get("mode"),
        "source_id": (context.get("source_id") or context.get("source")),
        "meter_id": context.get("meter_id"),
        "maximum_age_seconds": (
            context.get("maximum_age_seconds")
            or context.get("service_maximum_age_seconds")
        ),
    }

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )

    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
