"""Declarative catalogue of supervised repairs and their preconditions.

A repair is never inferred from words in an incident message. It applies only
to a declared service of the right type and implementation, after Tsunade has
recorded a deterministic diagnosis confirmed by the probe the repair relies on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.tsunade.incident_models import TsunadeIncident

RepairOperation = Literal["restart_service", "restart_addon"]


@dataclass(frozen=True, slots=True)
class RepairSpec:
    """One finite repair: symptom, preconditions, action, risk and verification."""

    key: str
    operation: RepairOperation
    target: str
    service_types: frozenset[str]
    implementation_terms: tuple[str, ...]
    probe_operation: str
    probe_confirms: Callable[[dict[str, Any]], bool]
    action: str
    question: str
    risk: Literal["low", "medium", "high"]
    consequences: tuple[str, ...]
    expected_result: str


def _dnsmasq_stopped(result: dict[str, Any]) -> bool:
    # A full lease pool also fails dhcp.status; restarting would not fix it.
    metadata = result.get("metadata") or {}
    return result.get("success") is False and metadata.get("service_active") is False


def _mqtt_round_trip_failed(result: dict[str, Any]) -> bool:
    return result.get("success") is False


REPAIRS: tuple[RepairSpec, ...] = (
    RepairSpec(
        key="dnsmasq.restart",
        operation="restart_service",
        target="dnsmasq.service",
        service_types=frozenset({"dhcp"}),
        implementation_terms=("dnsmasq",),
        probe_operation="dhcp.status",
        probe_confirms=_dnsmasq_stopped,
        action="le redémarrage supervisé de dnsmasq",
        question="Autoriser le redémarrage supervisé de dnsmasq ?",
        risk="low",
        consequences=(
            "Interruption brève du DHCP et de la résolution DNS locale.",
            "Aucune configuration réseau n’est modifiée.",
            "Shikamaru vérifie le retour de la capacité après l’action.",
        ),
        expected_result="dnsmasq est actif et le contrôle DHCP redevient sain.",
    ),
    RepairSpec(
        key="mosquitto.restart",
        operation="restart_addon",
        target="core_mosquitto",
        service_types=frozenset({"mqtt"}),
        implementation_terms=("mosquitto",),
        probe_operation="mqtt.status",
        probe_confirms=_mqtt_round_trip_failed,
        action="le redémarrage supervisé de l’add-on Mosquitto",
        question=(
            "Autoriser le redémarrage de l’add-on Mosquitto par le Supervisor "
            "Home Assistant ?"
        ),
        risk="low",
        consequences=(
            "Les clients MQTT (Zigbee2MQTT, Téléinformation, capteurs) sont "
            "déconnectés pendant le redémarrage.",
            "La configuration de l’add-on n’est pas modifiée.",
            "Shikamaru vérifie l’aller-retour MQTT après l’action.",
        ),
        expected_result="L’aller-retour MQTT vers le broker réussit de nouveau.",
    ),
)


def repair_spec(operation: str, target: str) -> RepairSpec | None:
    """Return the catalogue entry of a persisted repair."""
    return next(
        (
            spec
            for spec in REPAIRS
            if spec.operation == operation and spec.target == target
        ),
        None,
    )


def eligible_repair(
    incident: TsunadeIncident,
    infrastructure: InfrastructureConfig,
) -> RepairSpec:
    """Return the only repair whose preconditions the incident satisfies."""
    if incident.state != "active":
        raise ValueError("Une réparation exige un incident actif")
    service = next(
        (item for item in infrastructure.services if item.id == incident.service_id),
        None,
    )
    if service is None:
        raise ValueError("Le service de cet incident n’est pas déclaré")
    implementation = (service.implementation or "").casefold()
    spec = next(
        (
            candidate
            for candidate in REPAIRS
            if service.type in candidate.service_types
            and any(term in implementation for term in candidate.implementation_terms)
        ),
        None,
    )
    if spec is None:
        raise ValueError("Aucune réparation connue ne correspond à ce service")
    decision = incident.latest_decision or {}
    if decision.get("epistemic_status") != "confirmed_by_probe":
        raise ValueError(
            "La réparation exige un diagnostic confirmé par une sonde déterministe"
        )
    probe = _latest_probe(incident, spec.probe_operation)
    if probe is None or not spec.probe_confirms(probe):
        raise ValueError(
            f"La sonde {spec.probe_operation} ne confirme pas le symptôme "
            "que cette réparation corrige"
        )
    return spec


def _latest_probe(incident: TsunadeIncident, operation: str) -> dict[str, Any] | None:
    for event in reversed(incident.events):
        payload = event.payload
        if (
            event.kind == "investigation"
            and payload.get("operation") == operation
            and payload.get("status") == "OK"
        ):
            result = payload.get("result")
            return result if isinstance(result, dict) else None
    return None
