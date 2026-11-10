"""An incident is critical only for what the infrastructure declares critical."""

import os
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.incident_severity import (
    DeclaredSeverity,
    declared_severity,
    observed_severity,
)
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository


def _server(node: str) -> dict[str, str]:
    return {"id": node, "label": node.upper(), "kind": "server", "node": node}


INFRASTRUCTURE = {
    "infrastructure": {"id": "konoha", "name": "Konoha"},
    "nodes": [
        {
            "id": node,
            "name": node.upper(),
            "endpoint": {"type": "ip", "address": f"192.168.1.{index}"},
        }
        for index, node in enumerate(("infra-01", "linky-01", "sun-01"), 10)
    ],
    "services": [
        {
            "id": "dhcp-primary",
            "name": "DHCP",
            "type": "dhcp",
            "node": "infra-01",
            "critical": True,
        },
        {
            "id": "teleinformation",
            "name": "Téléinformation",
            "type": "teleinformation",
            "node": "linky-01",
            "critical": False,
        },
        {
            "id": "ntp-off",
            "name": "NTP désactivé",
            "type": "ntp",
            "node": "sun-01",
            "enabled": False,
            "critical": True,
        },
    ],
    "topology": {
        "devices": [
            {
                "id": "infra-01",
                "label": "INFRA-01",
                "kind": "server",
                "node": "infra-01",
            },
            {
                "id": "linky-01",
                "label": "LINKY-01",
                "kind": "server",
                "node": "linky-01",
            },
            _server("sun-01"),
            {
                "id": "vac-01",
                "label": "VAC-01",
                "kind": "smart_device",
                "address": "192.168.1.60",
            },
            {
                "id": "box-01",
                "label": "BOX-01",
                "kind": "router",
                "address": "192.168.1.1",
                "metadata": {"critical": True},
            },
            {
                "id": "infra-spare",
                "label": "INFRA-SPARE",
                "kind": "server",
                "node": "infra-01",
                "metadata": {"critical": False},
            },
        ]
    },
}


def _infrastructure() -> InfrastructureConfig:
    return InfrastructureConfig.model_validate(INFRASTRUCTURE)


def _observation(
    node: str,
    service: str,
    capability: str = "dhcp.status",
    *,
    status: ObservationStatus = ObservationStatus.UNHEALTHY,
    device: str | None = None,
) -> Observation:
    return Observation(
        node=node,
        service=service,
        capability=capability,
        status=status,
        success=status is ObservationStatus.HEALTHY,
        message="contrôle",
        source=capability,
        timestamp=datetime(2026, 11, 10, 12, tzinfo=UTC),
        metadata={"target_type": "device", "device_id": device} if device else {},
    )


def _presence(device: str, node: str | None = None) -> Observation:
    return _observation(node or device, device, "network.reachable", device=device)


def test_a_failed_service_is_critical_only_when_declared_critical() -> None:
    infrastructure = _infrastructure()

    assert (
        declared_severity(_observation("infra-01", "dhcp-primary"), infrastructure)
        == "critical"
    )
    assert (
        declared_severity(
            _observation("linky-01", "teleinformation", "teleinformation.freshness"),
            infrastructure,
        )
        == "degraded"
    )


def test_a_degraded_or_healthy_observation_ignores_the_declaration() -> None:
    infrastructure = _infrastructure()

    assert (
        declared_severity(
            _observation("infra-01", "dhcp-primary", status=ObservationStatus.DEGRADED),
            infrastructure,
        )
        == "degraded"
    )
    for status in (ObservationStatus.HEALTHY, ObservationStatus.UNKNOWN):
        assert (
            declared_severity(
                _observation("infra-01", "dhcp-primary", status=status), infrastructure
            )
            is None
        )


def test_an_absent_equipment_is_critical_when_it_hosts_a_critical_service() -> None:
    infrastructure = _infrastructure()

    assert declared_severity(_presence("infra-01"), infrastructure) == "critical"
    # LINKY-01 only hosts a secondary service, SUN-01 a disabled one.
    assert declared_severity(_presence("linky-01"), infrastructure) == "degraded"
    assert declared_severity(_presence("sun-01"), infrastructure) == "degraded"
    assert declared_severity(_presence("vac-01"), infrastructure) == "degraded"


def test_the_equipment_flag_wins_over_the_services_it_hosts() -> None:
    infrastructure = _infrastructure()

    assert declared_severity(_presence("box-01"), infrastructure) == "critical"
    assert (
        declared_severity(_presence("infra-spare", "infra-01"), infrastructure)
        == "degraded"
    )


def test_a_discovered_equipment_is_never_critical() -> None:
    node = _observation(
        "zwave-01", "zwave-node-12", "zwave.node.alive", device="zwave-node-12"
    )

    assert declared_severity(node, _infrastructure()) == "degraded"


def test_what_the_infrastructure_does_not_describe_keeps_its_severity() -> None:
    host = _observation("infra-01", "host", "host.health")
    backup = _observation("ha-01", "ha-01", "backup.run")

    assert declared_severity(host, _infrastructure()) == "critical"
    assert declared_severity(backup, _infrastructure()) == "critical"
    assert declared_severity(host, None) == observed_severity(host) == "critical"


def test_the_policy_follows_the_infrastructure_file(tmp_path: Path) -> None:
    path = tmp_path / "infrastructure.yaml"
    policy = DeclaredSeverity(path)
    failure = _observation("linky-01", "teleinformation", "teleinformation.freshness")

    # No readable declaration: the failure is not hidden.
    assert policy(failure) == "critical"

    path.write_text(yaml.safe_dump(INFRASTRUCTURE), encoding="utf-8")
    assert policy(failure) == "degraded"

    changed = yaml.safe_load(yaml.safe_dump(INFRASTRUCTURE))
    changed["services"][1]["critical"] = True
    path.write_text(yaml.safe_dump(changed), encoding="utf-8")
    os.utime(path, ns=(1, path.stat().st_mtime_ns + 1_000_000_000))
    assert policy(failure) == "critical"

    path.write_text("services: [", encoding="utf-8")
    os.utime(path, ns=(1, path.stat().st_mtime_ns + 2_000_000_000))
    assert policy(failure) == "critical"


def test_the_repository_opens_and_requalifies_incidents_with_the_policy(
    tmp_path: Path,
) -> None:
    critical = {"teleinformation": False}

    def policy(observation: Observation):
        if observation.status is not ObservationStatus.UNHEALTHY:
            return observed_severity(observation)
        return "critical" if critical[observation.service] else "degraded"

    repository = TsunadeIncidentRepository(tmp_path / "control.db", severity=policy)
    failure = _observation("linky-01", "teleinformation", "teleinformation.freshness")
    try:
        opened = repository.process(failure)
        assert opened is not None and opened.severity == "degraded"

        critical["teleinformation"] = True
        later = Observation(
            node=failure.node,
            service=failure.service,
            capability=failure.capability,
            status=failure.status,
            success=False,
            message="contrôle",
            source=failure.source,
            timestamp=datetime(2026, 11, 10, 12, 5, tzinfo=UTC),
        )
        escalated = repository.process(later)
        assert escalated is not None and escalated.severity == "critical"
        assert escalated.incident_id == opened.incident_id
        assert escalated.events[-1].kind == "escalated"
    finally:
        repository.close()


def test_without_a_policy_every_failed_check_stays_critical(tmp_path: Path) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    try:
        opened = repository.process(
            _observation("linky-01", "teleinformation", "teleinformation.freshness")
        )
        assert opened is not None and opened.severity == "critical"
    finally:
        repository.close()
