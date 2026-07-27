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

    assert len(tasks) == 1
    assert tasks[0].command == "dns.resolve"
    assert tasks[0].arguments == {
        "hostname": "example.com",
        "server": "192.168.1.10",
        "service_id": "dns-primary",
    }
    assert tasks[0].metadata == {
        "managed_by": "dns",
        "service_id": "dns-primary",
        "server": "192.168.1.10",
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
    )

    agent.start()
    agent.tick()
    agent.stop()

    assert [operation for operation, _payload in vision_client.operations] == [
        "infrastructure",
        "observation",
    ]

    infrastructure_payload = vision_client.operations[0][1]

    assert infrastructure_payload["infrastructure_id"] == ("ohana-house")
    assert len(infrastructure_payload["topology"]["devices"]) == 9
    assert len(infrastructure_payload["topology"]["links"]) == 8
    assert len(infrastructure_payload["topology"]["layouts"]) == 1

    observation_payload = vision_client.operations[1][1]

    assert observation_payload["node_id"] == "infra-01"
    assert observation_payload["service_id"] == "dns-primary"
    assert observation_payload["capability_id"] == "dns.resolve"
    assert observation_payload["status"] in {
        "healthy",
        "unavailable",
    }
    assert observation_payload["metadata"]["hostname"] == ("example.com")
    assert observation_payload["metadata"]["server"] == ("192.168.1.10")


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

    tasks = agent.scheduler.list_tasks()
    assert [task.arguments["service_id"] for task in tasks] == [
        "dns-primary",
        "dns-secondary",
    ]
    assert len(agent.scheduler.due_tasks()) == 2
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

    tasks = agent.scheduler.list_tasks()
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

    assert agent.scheduler.list_tasks() == []
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
