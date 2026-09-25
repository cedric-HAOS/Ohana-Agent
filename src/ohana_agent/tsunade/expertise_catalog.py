"""Tsunade decisions, known procedures and expertise outcomes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from ohana_agent.contracts.administration import (
    AdministrationModel,
)
from ohana_agent.tsunade.incident_models import (
    TsunadeIncident,
)

HOME_ASSISTANT_ENTITY_ID = re.compile(r"\b[a-z][a-z0-9_]*\.[a-z0-9_]+\b", re.IGNORECASE)

TsunadeDecision = Literal[
    "stable",
    "watch",
    "investigate",
    "action_required",
]

TsunadeDecisionSource = Literal[
    "deterministic",
    "katsuyu_ai",
    "fallback",
]


@dataclass(frozen=True, slots=True)
class TsunadeDecisionResult:
    """One bounded decision owned by Tsunade."""

    decision: TsunadeDecision
    source: TsunadeDecisionSource
    conclusion: str
    reason: str
    confidence: float
    recommended_action: str
    reevaluate_after: str | None = None


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
    # Before "dns": a dnsmasq message would otherwise select the DNS procedure.
    KnownProcedure(
        ("dhcp",),
        ("dhcp.status",),
        "Le service DHCP local échoue à une vérification déterministe.",
        ("Vérifier l’état de dnsmasq et son pool d’adresses avant d’intervenir.",),
    ),
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
    decision: TsunadeDecision | None = None
    decision_source: TsunadeDecisionSource | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


def _teleinformation_addon_state(
    incident: TsunadeIncident,
    diagnostics: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    """Extract the current teleinfo2mqtt Supervisor state when relevant."""

    if incident.capability_id != "teleinformation.freshness":
        return None, None

    context = incident.context

    if context.get("mode") != "direct_http":
        return None, None

    if not isinstance(diagnostics, dict):
        return None, None

    inspection = diagnostics.get("configuration_inspection")

    if not isinstance(inspection, dict):
        return None, None

    remote = inspection.get("remote")

    if not isinstance(remote, dict):
        return None, None

    addons = remote.get("addons")

    if not isinstance(addons, list):
        return None, None

    for addon in addons:
        if not isinstance(addon, dict):
            continue

        addon_id = str(addon.get("addon") or "")
        normalized = addon_id.casefold()

        if "teleinfo" not in normalized:
            continue

        state = str(addon.get("state") or "").strip().casefold()

        return state or None, addon_id or None

    return None, None
