from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bootstrap import build_production_agent
from configuration.infrastructure import (
    NodeConfig,
    NodeEndpointConfig,
    ServiceConfig,
)
from loader import InfrastructureLoader
from observer.exporters import VisionInfrastructureMapper
from plugins.network.network_probe_result import NetworkProbeResult
from scheduler.clock import FakeClock


@dataclass
class FakeVisionClient:
    """Capture data exported by the production bootstrap."""

    operations: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def send_observation(
        self,
        payload: dict[str, Any],
    ) -> None:
        self.operations.append(("observation", payload))

    def send_infrastructure(
        self,
        payload: dict[str, Any],
    ) -> None:
        self.operations.append(("infrastructure", payload))


class FakeNetworkCheck:
    """Return a deterministic reachable result for bootstrap tests."""

    def check(
        self,
        address: str,
        *,
        timeout: float,
        retries: int,
    ) -> NetworkProbeResult:
        del timeout, retries
        return NetworkProbeResult(
            address=address,
            reachable=True,
            method="icmp",
            latency_ms=1.0,
        )


def test_production_bootstrap_builds_dns_task() -> None:
    clock = FakeClock(
        current_time=datetime(
            2026,
            7,
            15,
            12,
            0,
            tzinfo=UTC,
        )
    )

    agent = build_production_agent(
        application_config_path=Path("config/shikamaru.yaml"),
        infrastructure_config_path=Path("config/infrastructure.yaml"),
        dns_config_path=Path("config/plugins/dns.yaml"),
        vision_client=FakeVisionClient(),
        clock=clock,
    )

    tasks = agent.scheduler.list_tasks()
    dns_tasks = [task for task in tasks if task.command == "dns.resolve"]
    network_tasks = [task for task in tasks if task.command == "network.reachable"]

    assert len(dns_tasks) == 1
    assert len(network_tasks) == 1
    assert dns_tasks[0].arguments == {
        "hostname": "example.com",
        "server": "192.168.1.10",
        "service_id": "dns-primary",
    }
    assert dns_tasks[0].metadata == {
        "managed_by": "dns",
        "service_id": "dns-primary",
        "server": "192.168.1.10",
    }
    assert network_tasks[0].arguments == {
        "address": "192.168.1.10",
        "device_id": "rpi-link",
        "label": "RPI-LINK",
        "node_id": "infra-01",
    }
    assert network_tasks[0].metadata == {
        "managed_by": "network",
        "device_id": "rpi-link",
        "address": "192.168.1.10",
    }
    assert agent.infrastructure_retry_seconds == 10.0
    assert agent.infrastructure_refresh_seconds == 300.0
    assert agent.infrastructure_payload is not None
    assert len(agent.infrastructure_payload["topology"]["devices"]) == 9
    assert len(agent.infrastructure_payload["topology"]["links"]) == 8


def test_production_bootstrap_exports_infrastructure_before_observation() -> None:
    clock = FakeClock(
        current_time=datetime(
            2026,
            7,
            15,
            12,
            0,
            tzinfo=UTC,
        )
    )
    vision_client = FakeVisionClient()

    agent = build_production_agent(
        vision_client=vision_client,
        clock=clock,
        network_check=FakeNetworkCheck(),
    )

    agent.start()
    agent.tick()
    agent.stop()

    assert [operation for operation, _payload in vision_client.operations] == [
        "infrastructure",
        "observation",
        "observation",
    ]

    infrastructure_payload = vision_client.operations[0][1]

    assert infrastructure_payload["infrastructure_id"] == ("ohana-house")
    assert len(infrastructure_payload["topology"]["devices"]) == 9
    assert len(infrastructure_payload["topology"]["links"]) == 8
    assert len(infrastructure_payload["topology"]["layouts"]) == 1

    observations = {
        payload["capability_id"]: payload
        for operation, payload in vision_client.operations
        if operation == "observation"
    }

    dns_observation = observations["dns.resolve"]
    assert dns_observation["node_id"] == "infra-01"
    assert dns_observation["service_id"] == "dns-primary"
    assert dns_observation["status"] in {
        "healthy",
        "unavailable",
    }
    assert dns_observation["metadata"]["hostname"] == "example.com"
    assert dns_observation["metadata"]["server"] == "192.168.1.10"

    network_observation = observations["network.reachable"]
    assert network_observation["node_id"] == "infra-01"
    assert network_observation["service_id"] == "rpi-link"
    assert network_observation["status"] == "healthy"
    assert network_observation["metadata"]["device_id"] == "rpi-link"
    assert network_observation["metadata"]["address"] == "192.168.1.10"


def test_production_bootstrap_reconfigures_dns_tasks_from_infrastructure() -> None:
    clock = FakeClock(
        current_time=datetime(
            2026,
            7,
            15,
            12,
            0,
            tzinfo=UTC,
        )
    )
    client = FakeVisionClient()
    agent = build_production_agent(
        vision_client=client,
        clock=clock,
    )
    configuration = InfrastructureLoader().load(Path("config/infrastructure.yaml"))
    configuration_with_secondary = configuration.model_copy(
        update={
            "nodes": [
                *configuration.nodes,
                NodeConfig(
                    id="dns-02",
                    name="DNS-02",
                    endpoint=NodeEndpointConfig(
                        type="ip",
                        address="192.168.1.12",
                    ),
                ),
            ],
            "services": [
                *configuration.services,
                ServiceConfig(
                    id="dns-secondary",
                    name="DNS secondaire",
                    type="dns",
                    node="dns-02",
                    port=53,
                ),
            ],
        }
    )

    agent.start()
    agent.apply_infrastructure_configuration(
        configuration_with_secondary,
        VisionInfrastructureMapper().to_payload(configuration_with_secondary),
    )

    tasks = [
        task
        for task in agent.scheduler.list_tasks()
        if task.command == "dns.resolve"
    ]
    assert [task.arguments["service_id"] for task in tasks] == [
        "dns-primary",
        "dns-secondary",
    ]
    assert len([
        task
        for task in agent.scheduler.due_tasks()
        if task.command == "dns.resolve"
    ]) == 2
    assert agent.scheduler.running is True

    configuration_without_primary = configuration_with_secondary.model_copy(
        update={
            "services": [
                service
                for service in configuration_with_secondary.services
                if service.id != "dns-primary"
            ]
        }
    )
    agent.apply_infrastructure_configuration(
        configuration_without_primary,
        VisionInfrastructureMapper().to_payload(configuration_without_primary),
    )

    tasks = [
        task
        for task in agent.scheduler.list_tasks()
        if task.command == "dns.resolve"
    ]
    assert [task.arguments["service_id"] for task in tasks] == ["dns-secondary"]
    assert agent.scheduler.running is True

    configuration_without_dns = configuration_without_primary.model_copy(
        update={
            "services": [
                service
                for service in configuration_without_primary.services
                if service.type != "dns"
            ]
        }
    )
    agent.apply_infrastructure_configuration(
        configuration_without_dns,
        VisionInfrastructureMapper().to_payload(configuration_without_dns),
    )

    assert [
        task
        for task in agent.scheduler.list_tasks()
        if task.command == "dns.resolve"
    ] == []
    assert agent.scheduler.running is True

    agent.stop()


def test_production_bootstrap_reconfigures_ntp_tasks_from_infrastructure() -> None:
    clock = FakeClock(
        current_time=datetime(
            2026,
            7,
            15,
            12,
            0,
            tzinfo=UTC,
        )
    )
    client = FakeVisionClient()
    agent = build_production_agent(
        vision_client=client,
        clock=clock,
    )
    configuration = InfrastructureLoader().load(Path("config/infrastructure.yaml"))
    configuration_with_ntp = configuration.model_copy(
        update={
            "services": [
                *configuration.services,
                ServiceConfig(
                    id="ntp-primary",
                    name="NTP principal",
                    type="ntp",
                    node="infra-01",
                    port=123,
                ),
            ]
        }
    )

    agent.start()
    agent.apply_infrastructure_configuration(
        configuration_with_ntp,
        VisionInfrastructureMapper().to_payload(configuration_with_ntp),
    )

    tasks = agent.scheduler.list_tasks()
    ntp_tasks = [task for task in tasks if task.command == "ntp.query"]

    assert len(ntp_tasks) == 1
    assert ntp_tasks[0].arguments == {
        "server": "192.168.1.10",
        "port": 123,
        "service_id": "ntp-primary",
    }
    assert ntp_tasks[0].metadata == {
        "managed_by": "ntp",
        "service_id": "ntp-primary",
        "server": "192.168.1.10",
        "port": 123,
    }

    configuration_without_ntp = configuration_with_ntp.model_copy(
        update={
            "services": [
                service
                for service in configuration_with_ntp.services
                if service.type != "ntp"
            ]
        }
    )
    agent.apply_infrastructure_configuration(
        configuration_without_ntp,
        VisionInfrastructureMapper().to_payload(configuration_without_ntp),
    )

    assert [
        task for task in agent.scheduler.list_tasks() if task.command == "ntp.query"
    ] == []
    assert agent.scheduler.running is True

    agent.stop()


def test_production_bootstrap_reconfigures_mqtt_tasks_from_infrastructure() -> None:
    clock = FakeClock(
        current_time=datetime(
            2026,
            7,
            15,
            12,
            0,
            tzinfo=UTC,
        )
    )
    client = FakeVisionClient()
    agent = build_production_agent(
        vision_client=client,
        clock=clock,
    )
    configuration = InfrastructureLoader().load(Path("config/infrastructure.yaml"))
    configuration_with_mqtt = configuration.model_copy(
        update={
            "services": [
                *configuration.services,
                ServiceConfig(
                    id="mqtt-primary",
                    name="MQTT principal",
                    type="mqtt",
                    node="infra-01",
                    port=1883,
                ),
            ]
        }
    )

    agent.start()
    agent.apply_infrastructure_configuration(
        configuration_with_mqtt,
        VisionInfrastructureMapper().to_payload(configuration_with_mqtt),
    )

    tasks = agent.scheduler.list_tasks()
    mqtt_tasks = [task for task in tasks if task.command == "mqtt.roundtrip"]

    assert len(mqtt_tasks) == 1
    assert mqtt_tasks[0].arguments == {
        "broker": "192.168.1.10",
        "port": 1883,
        "service_id": "mqtt-primary",
    }
    assert mqtt_tasks[0].metadata == {
        "managed_by": "mqtt",
        "service_id": "mqtt-primary",
        "broker": "192.168.1.10",
        "port": 1883,
    }

    configuration_without_mqtt = configuration_with_mqtt.model_copy(
        update={
            "services": [
                service
                for service in configuration_with_mqtt.services
                if service.type != "mqtt"
            ]
        }
    )
    agent.apply_infrastructure_configuration(
        configuration_without_mqtt,
        VisionInfrastructureMapper().to_payload(configuration_without_mqtt),
    )

    assert [
        task
        for task in agent.scheduler.list_tasks()
        if task.command == "mqtt.roundtrip"
    ] == []
    assert agent.scheduler.running is True

    agent.stop()
