"""Name the component behind a log anomaly, so it can be read and accepted.

Katsuyu groups anomalies by signature: for HA-01 that is 38 lines such as
``[custom_components.tapo_control] httpsconnectionpool(host=...``, spread over
a dozen integrations. The user thinks in integrations ("Tapo", "Kasa"), not in
signatures, and the variants of one failure keep changing. The component is
read from what the signature already contains: nothing is guessed.
"""

from __future__ import annotations

import re
from typing import Any

# Known third-party integrations and libraries: logger root -> display name.
_DISPLAY_NAMES = {
    "aioesphomeapi": "ESPHome",
    "aioshelly": "Shelly",
    "esphome": "ESPHome",
    "kasa": "Kasa",
    "mqtt": "MQTT",
    "paho": "MQTT",
    "roombapy": "Roomba",
    "roomba": "Roomba",
    "shelly": "Shelly",
    "tapo": "Tapo",
    "tapo_control": "Tapo",
    "template": "Modèles Home Assistant",
    "iaqualink": "iAquaLink",
    "iaqualinkrobots": "iAquaLink",
    "rte_tempo": "RTE Tempo",
    "zwave_js": "Z-Wave JS",
    "hass_nabucasa": "Home Assistant Cloud",
    "async_upnp_client": "UPnP",
    "pysmartthings": "SmartThings",
    "co2signal": "CO2 Signal",
    "tplink": "TP-Link",
    "meteo_france": "Météo-France",
    "zeroconf": "Zeroconf",
}
# A library and its Home Assistant integration are one component for the user:
# "aioshelly" and "homeassistant.components.shelly" both name Shelly.
_ALIASES = {
    "aioesphomeapi": "esphome",
    "aioshelly": "shelly",
    "paho": "mqtt",
    "roombapy": "roomba",
    "snitun": "hass_nabucasa",
    "tapo": "tapo_control",
}
_OHANA_UNITS = {
    "ohana-agent": "Ohana Agent",
    "ohana-vision": "Ohana Vision",
    "ohana-katsuyu": "Ohana Katsuyu",
}
# The logger of a Home Assistant line: "[custom_components.tapo_control]".
_LOGGER = re.compile(r"\(\w[\w\- ]*\)\s*\[([a-z0-9_.\-]+)\]")
_BRACKETED = re.compile(r"\[([a-z][a-z0-9_.\-]*)\]")
_SYSTEMD_UNIT = re.compile(r"\b(ohana-[a-z]+)\[")
_ADDON = re.compile(r"\b(teleinfo2mqtt)\b")
OTHER = ("other", "Autre")


def canonical_component(component: str) -> str:
    """The component id an accepted or displayed id stands for today."""
    return _ALIASES.get(component, component)


def component_label(component: str, fallback: str | None = None) -> str:
    """Display name of a component id; ``fallback`` for ids without a rule."""
    known = _DISPLAY_NAMES.get(canonical_component(component))
    if known:
        return known
    return fallback or _title(component)


def _title(name: str) -> str:
    return _DISPLAY_NAMES.get(name) or name.replace("_", " ").replace("-", " ").title()


def log_component(finding: dict[str, Any]) -> tuple[str, str]:
    """Return (component id, display name) for one grouped log anomaly."""
    signature = str(finding.get("signature") or "")
    unit = _SYSTEMD_UNIT.search(signature)
    if unit is not None:
        return unit.group(1), _OHANA_UNITS.get(unit.group(1), _title(unit.group(1)))
    logger_match = _LOGGER.search(signature) or _BRACKETED.search(signature)
    if logger_match is not None:
        parts = logger_match.group(1).split(".")
        if parts[0] == "custom_components" and len(parts) > 1:
            root = _ALIASES.get(parts[1], parts[1])
            return root, _title(root)
        if parts[0] == "homeassistant" and len(parts) > 2 and parts[1] == "components":
            if parts[2] == "automation" and len(parts) > 3:
                # One automation is one thing the user wrote and can fix.
                return f"automation.{parts[3]}", f"Automatisation {_title(parts[3])}"
            root = _ALIASES.get(parts[2], parts[2])
            return root, _title(root)
        if parts[0] == "homeassistant":
            return "homeassistant", "Home Assistant"
        root = _ALIASES.get(parts[0], parts[0])
        return root, _title(root)
    if _ADDON.search(signature):
        return "teleinfo2mqtt", "teleinfo2mqtt"
    if "cntrlr" in signature:
        return "zwave_js.controller", "Z-Wave JS (contrôleur)"
    return OTHER


def annotate_log_finding(finding: dict[str, Any]) -> dict[str, Any]:
    """Return the finding with its component; the input is left untouched."""
    component, label = log_component(finding)
    return {**finding, "component": component, "component_label": label}


def component_overview(
    sources: list[Any], accepted: dict[str, set[str]]
) -> list[dict[str, Any]]:
    """Group each source's findings by component, with what is accepted."""
    order = {"critical": 0, "error": 1, "warning": 2}
    overview: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source", ""))
        groups: dict[str, dict[str, Any]] = {}
        for raw in source.get("findings") or []:
            if not isinstance(raw, dict):
                continue
            finding = annotate_log_finding(raw)
            group = groups.setdefault(
                finding["component"],
                {
                    "component": finding["component"],
                    "label": finding["component_label"],
                    "signatures": 0,
                    "occurrences": 0,
                    "severity": "warning",
                    "accepted": finding["component"] in accepted.get(source_id, set()),
                },
            )
            group["signatures"] += 1
            group["occurrences"] += int(finding.get("occurrences") or 0)
            severity = str(finding.get("severity") or "warning")
            if order.get(severity, 3) < order.get(group["severity"], 3):
                group["severity"] = severity
        overview.append(
            {
                "source": source_id,
                "components": sorted(
                    groups.values(),
                    key=lambda item: (
                        order.get(item["severity"], 3),
                        -item["occurrences"],
                    ),
                ),
            }
        )
    return overview
