"""Declarative catalogue of supervised repairs and their preconditions.

A repair is never inferred from words in an incident message. It applies only
to a declared service of the right type and implementation, after Tsunade has
recorded a deterministic diagnosis confirmed by the probe, or the Supervisor
state, the repair relies on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.tsunade.incident_models import TsunadeIncident

RepairOperation = Literal["restart_service", "restart_addon"]
RepairEvidence = Literal["confirmed_by_probe", "confirmed_by_supervisor"]


@dataclass(frozen=True, slots=True)
class RepairSpec:
    """One finite repair: symptom, preconditions, action, risk and verification."""

    key: str
    operation: RepairOperation
    target: str
    service_types: frozenset[str]
    # Empty: the confirming probe itself identifies the implementation.
    implementation_terms: tuple[str, ...]
    action: str
    question: str
    risk: Literal["low", "medium", "high"]
    consequences: tuple[str, ...]
    expected_result: str
    evidence: RepairEvidence = "confirmed_by_probe"
    probe_operation: str | None = None
    probe_confirms: Callable[[dict[str, Any]], bool] | None = None
    # When set, the target is the add-on the Supervisor listed for the
    # incident's node: repository prefixes differ between installations.
    addon_terms: tuple[str, ...] = ()
    addon_states: frozenset[str] | None = None
    # The action runs on the Agent host: a service declared elsewhere is not
    # the one the local probe measured.
    agent_node_only: bool = False

    def targets(self, target: str) -> bool:
        if self.addon_terms:
            return _valid_slug(target) and _addon_matches(target, self.addon_terms)
        return self.target == target


def _dnsmasq_stopped(result: dict[str, Any]) -> bool:
    # A full lease pool also fails dhcp.status; restarting would not fix it.
    metadata = result.get("metadata") or {}
    return result.get("success") is False and metadata.get("service_active") is False


def _round_trip_failed(result: dict[str, Any]) -> bool:
    return result.get("success") is False


def _chrony_stopped(result: dict[str, Any]) -> bool:
    # Unreachable upstream sources also fail ntp.status; a restart would not
    # fix them, so only an inactive local chrony qualifies.
    return result.get("success") is False and result.get("service_active") is False


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
        probe_confirms=_round_trip_failed,
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
    RepairSpec(
        key="teleinfo2mqtt.restart",
        operation="restart_addon",
        target="",
        service_types=frozenset({"teleinformation"}),
        implementation_terms=("teleinfo",),
        evidence="confirmed_by_supervisor",
        addon_terms=("teleinfo",),
        # "started" with stale frames is not explained by the add-on state.
        addon_states=frozenset({"stopped", "error"}),
        action="le redémarrage supervisé de l’add-on teleinfo2mqtt",
        question=(
            "Autoriser le redémarrage de l’add-on teleinfo2mqtt par le Supervisor "
            "Home Assistant ?"
        ),
        risk="low",
        consequences=(
            "Aucune trame Téléinformation n’est publiée pendant le redémarrage.",
            "La configuration de l’add-on et le port série ne sont pas modifiés.",
            "Shikamaru vérifie la fraîcheur des trames après l’action.",
        ),
        expected_result="Les trames Téléinformation parviennent de nouveau à Agent.",
    ),
    RepairSpec(
        key="zwave_js.restart",
        operation="restart_addon",
        target="",
        service_types=frozenset({"zwave"}),
        implementation_terms=("z-wave js", "zwave js", "zwavejs", "zwave_js"),
        probe_operation="zwave.status",
        probe_confirms=_round_trip_failed,
        addon_terms=("zwavejs", "zwave_js"),
        action="le redémarrage supervisé de l’add-on Z-Wave JS",
        question=(
            "Autoriser le redémarrage de l’add-on Z-Wave JS par le Supervisor "
            "Home Assistant ?"
        ),
        # Longer than an MQTT restart: the driver re-interviews the network.
        risk="medium",
        consequences=(
            "Les équipements Z-Wave ne sont pas pilotables pendant le "
            "redémarrage et la réinitialisation du contrôleur.",
            "Le réseau Z-Wave, ses inclusions et la configuration de l’add-on "
            "ne sont pas modifiés.",
            "Shikamaru vérifie que le pilote Z-Wave JS redevient prêt après l’action.",
        ),
        expected_result="Le pilote Z-Wave JS répond et le contrôleur est prêt.",
    ),
    RepairSpec(
        key="chrony.restart",
        operation="restart_service",
        target="chrony.service",
        service_types=frozenset({"ntp"}),
        implementation_terms=(),
        probe_operation="chrony.status",
        probe_confirms=_chrony_stopped,
        agent_node_only=True,
        action="le redémarrage supervisé de chrony",
        question="Autoriser le redémarrage supervisé de chrony ?",
        risk="low",
        consequences=(
            "Le service de temps du réseau local est indisponible quelques secondes.",
            "Aucune configuration de chrony ni source amont n’est modifiée.",
            "Shikamaru vérifie la réponse NTP après l’action.",
        ),
        expected_result="chrony est actif et répond de nouveau aux requêtes NTP.",
    ),
)


def repair_spec(operation: str, target: str) -> RepairSpec | None:
    """Return the catalogue entry of a persisted repair, with its target."""
    spec = next(
        (
            spec
            for spec in REPAIRS
            if spec.operation == operation and spec.targets(target)
        ),
        None,
    )
    return replace(spec, target=target) if spec is not None else None


def eligible_repair(
    incident: TsunadeIncident,
    infrastructure: InfrastructureConfig,
    *,
    agent_node_id: str | None = None,
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
            and _implements(implementation, candidate.implementation_terms)
        ),
        None,
    )
    if spec is None:
        raise ValueError("Aucune réparation connue ne correspond à ce service")
    if spec.agent_node_only and service.node != agent_node_id:
        raise ValueError(
            "Cette réparation n’agit que sur l’hôte de l’Agent ; le service "
            f"est déclaré sur {service.node}"
        )
    decision = incident.latest_decision or {}
    if decision.get("epistemic_status") != spec.evidence:
        raise ValueError(
            "La réparation exige un diagnostic confirmé par une sonde déterministe"
            if spec.evidence == "confirmed_by_probe"
            else "La réparation exige un diagnostic confirmé par le Supervisor"
        )
    if spec.probe_operation is not None:
        probe = _latest_probe(incident, spec.probe_operation)
        if (
            probe is None
            or spec.probe_confirms is None
            or not spec.probe_confirms(probe)
        ):
            raise ValueError(
                f"La sonde {spec.probe_operation} ne confirme pas le symptôme "
                "que cette réparation corrige"
            )
    if spec.addon_terms:
        return replace(spec, target=_observed_addon(incident, spec))
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


def _observed_addon(incident: TsunadeIncident, spec: RepairSpec) -> str:
    """Return the add-on the latest Supervisor inspection of the node listed."""
    for event in reversed(incident.events):
        if (
            event.kind != "investigation"
            or "configuration_inspection" not in event.payload
        ):
            continue
        # Only the latest inspection describes the current add-ons: an
        # unavailable Supervisor must not fall back to an older listing.
        inspection = event.payload["configuration_inspection"]
        remote = inspection.get("remote") if isinstance(inspection, dict) else None
        addons = remote.get("addons") if isinstance(remote, dict) else None
        for addon in addons if isinstance(addons, list) else ():
            if not isinstance(addon, dict):
                continue
            slug = str(addon.get("addon") or "")
            if not _valid_slug(slug) or not _addon_matches(slug, spec.addon_terms):
                continue
            state = str(addon.get("state") or "").strip().casefold()
            if spec.addon_states is not None and state not in spec.addon_states:
                raise ValueError(
                    f"Le Supervisor indique l’add-on {slug} dans l’état "
                    f"« {state or 'inconnu'} », que cette réparation ne corrige pas"
                )
            return slug
        break
    raise ValueError(
        "Aucun add-on correspondant n’a été observé par le Supervisor de "
        f"{incident.node_id}"
    )


def _implements(implementation: str, terms: tuple[str, ...]) -> bool:
    return not terms or any(term in implementation for term in terms)


def _addon_matches(slug: str, terms: tuple[str, ...]) -> bool:
    normalized = slug.casefold()
    return any(term in normalized for term in terms)


def _valid_slug(slug: str) -> bool:
    return bool(slug) and all(c.isalnum() or c in "_-" for c in slug)
