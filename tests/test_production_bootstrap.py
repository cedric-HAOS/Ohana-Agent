from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from bootstrap import build_production_agent
from configuration.infrastructure import (
    NodeConfig,
    NodeEndpointConfig,
    ServiceConfig,
)
from loader import InfrastructureLoader
from observer.exporters import VisionInfrastructureMapper
from plugins.dhcp.dhcp_check_result import DHCPCheckResult
from plugins.network.network_probe_result import NetworkProbeResult
from plugins.shelly_telemetry.shelly_telemetry_result import (
    ShellyTelemetryCheckResult,
    ShellyTelemetryValue,
)
from plugins.teleinformation.teleinformation_result import (
    TeleinformationCheckResult,
    TeleinformationTariff,
    TeleinformationValue,
)
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


class FakeDHCPCheck:
    """Return deterministic local DHCP state for bootstrap tests."""

    def check(
        self,
        server: str,
        *,
        port: int,
        service_id: str,
        main_config_path: Path,
        leases_path: Path,
        service_status_command: tuple[str, ...] | None,
        timeout: float,
    ) -> DHCPCheckResult:
        del main_config_path, leases_path, service_status_command, timeout
        return DHCPCheckResult(
            server=server,
            port=port,
            service_id=service_id,
            healthy=True,
            service_active=True,
            range_start="192.168.1.100",
            range_end="192.168.1.199",
            pool_size=100,
            lease_count=12,
            available_address_count=88,
            pool_usage_percent=12.0,
            status_output="active",
        )


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


class FakeShellyTelemetryCheck:
    """Return fresh Shelly telemetry without contacting Home Assistant."""

    def __init__(self) -> None:
        self.devices: list[str] = []

    def check(
        self,
        device_name: str,
        power_entity_id: str,
        *,
        energy_entity_id: str | None = None,
        home_assistant_url: str,
        access_token: str | None,
        access_token_environment_variable: str | None,
        maximum_age_seconds: int,
        timeout: float = 5.0,
        retries: int = 1,
        verify_tls: bool = True,
        now: datetime | None = None,
    ) -> ShellyTelemetryCheckResult:
        del (
            home_assistant_url,
            access_token,
            access_token_environment_variable,
            maximum_age_seconds,
            timeout,
            retries,
            verify_tls,
            now,
        )
        self.devices.append(device_name)
        return ShellyTelemetryCheckResult(
            device_name=device_name,
            healthy=True,
            power=ShellyTelemetryValue(
                entity_id=power_entity_id,
                value=1594.2,
                unit="W",
            ),
            energy=(
                ShellyTelemetryValue(
                    entity_id=energy_entity_id,
                    value=12.5,
                    unit="kWh",
                )
                if energy_entity_id is not None
                else None
            ),
        )


class FakeTeleinformationCheck:
    """Return fresh Linky data without contacting Home Assistant."""

    def __init__(self) -> None:
        self.meters: list[str] = []

    def check(
        self,
        meter_name: str,
        apparent_power_entity_id: str,
        tariff_entity_id: str,
        *,
        index_entity_ids: dict[str, str] | None = None,
        home_assistant_url: str,
        access_token: str | None,
        access_token_environment_variable: str | None,
        maximum_age_seconds: int,
        timeout: float = 5.0,
        retries: int = 1,
        verify_tls: bool = True,
        now: datetime | None = None,
    ) -> TeleinformationCheckResult:
        del (
            home_assistant_url,
            access_token,
            access_token_environment_variable,
            maximum_age_seconds,
            timeout,
            retries,
            verify_tls,
            now,
        )
        self.meters.append(meter_name)
        indexes = {
            key: TeleinformationValue(
                entity_id=entity_id,
                value=6931422.0 if key == "blue_peak" else 0.0,
                unit="Wh",
            )
            for key, entity_id in (index_entity_ids or {}).items()
        }
        return TeleinformationCheckResult(
            meter_name=meter_name,
            healthy=True,
            apparent_power=TeleinformationValue(
                entity_id=apparent_power_entity_id,
                value=1392.0,
                unit="VA",
            ),
            tariff_value=TeleinformationValue(
                entity_id=tariff_entity_id,
                value=2.0,
            ),
            tariff=TeleinformationTariff(
                number=2,
                color="Bleue",
                period="HP",
                label="HP Bleue",
                index_key="blue_peak",
            ),
            indexes=indexes,
            active_index=indexes.get("blue_peak"),
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
    dhcp_tasks = [task for task in tasks if task.command == "dhcp.status"]
    dns_tasks = [task for task in tasks if task.command == "dns.resolve"]
    network_tasks = [task for task in tasks if task.command == "network.reachable"]

    assert len(dhcp_tasks) == 1
    assert len(dns_tasks) == 1
    assert len(network_tasks) == 1
    assert dhcp_tasks[0].arguments == {
        "server": "192.168.1.10",
        "port": 67,
        "service_id": "dhcp-primary",
    }
    assert dhcp_tasks[0].metadata == {
        "managed_by": "dhcp",
        "node_id": "infra-01",
        "service_id": "dhcp-primary",
        "server": "192.168.1.10",
        "port": 67,
    }
    assert dns_tasks[0].arguments == {
        "hostname": "example.com",
        "server": "192.168.1.10",
        "service_id": "dns-primary",
    }
    assert dns_tasks[0].metadata == {
        "managed_by": "dns",
        "node_id": "infra-01",
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
        "node_id": "infra-01",
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
        dhcp_check=FakeDHCPCheck(),
    )

    agent.start()
    agent.tick()
    agent.stop()

    assert [operation for operation, _payload in vision_client.operations] == [
        "infrastructure",
        "observation",
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

    dhcp_observation = observations["dhcp.status"]
    assert dhcp_observation["node_id"] == "infra-01"
    assert dhcp_observation["service_id"] == "dhcp-primary"
    assert dhcp_observation["status"] == "healthy"
    assert dhcp_observation["metadata"]["lease_count"] == 12
    assert dhcp_observation["metadata"]["available_address_count"] == 88
    assert dhcp_observation["metadata"]["pool_usage_percent"] == 12.0

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
        task for task in agent.scheduler.list_tasks() if task.command == "dns.resolve"
    ]
    assert [task.arguments["service_id"] for task in tasks] == [
        "dns-primary",
        "dns-secondary",
    ]
    assert (
        len(
            [
                task
                for task in agent.scheduler.due_tasks()
                if task.command == "dns.resolve"
            ]
        )
        == 2
    )
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
        task for task in agent.scheduler.list_tasks() if task.command == "dns.resolve"
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
        task for task in agent.scheduler.list_tasks() if task.command == "dns.resolve"
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
        "node_id": "infra-01",
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
        "node_id": "infra-01",
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


def test_production_bootstrap_removes_dhcp_task_with_service() -> None:
    clock = FakeClock(current_time=datetime(2026, 7, 15, 12, 0, tzinfo=UTC))
    agent = build_production_agent(
        vision_client=FakeVisionClient(),
        clock=clock,
    )
    configuration = InfrastructureLoader().load(Path("config/infrastructure.yaml"))
    without_dhcp = configuration.model_copy(
        update={
            "services": [
                service for service in configuration.services if service.type != "dhcp"
            ]
        }
    )

    agent.start()
    agent.apply_infrastructure_configuration(
        without_dhcp,
        VisionInfrastructureMapper().to_payload(without_dhcp),
    )

    assert [
        task for task in agent.scheduler.list_tasks() if task.command == "dhcp.status"
    ] == []
    assert agent.scheduler.running is True

    agent.stop()


def test_shelly_plugin_reconfiguration_keeps_two_scheduled_services(
    tmp_path: Path,
) -> None:
    """Architecture and plugin updates must keep two Shelly tasks."""
    token_path = tmp_path / "management.token"
    token_path.write_text("test-token\n", encoding="utf-8")

    application_path = tmp_path / "shikamaru.yaml"
    application_path.write_text(
        f"""\
version: 1
agent:
  name: Shikamaru
  environment: test
vision:
  enabled: true
  observation_url: http://127.0.0.1:8000/api/observations
  infrastructure_url: http://127.0.0.1:8000/api/infrastructure
administration:
  enabled: true
  token_file: {token_path.as_posix()}
  dhcp:
    enabled: false
""",
        encoding="utf-8",
    )

    infrastructure = InfrastructureLoader().load(Path("config/infrastructure.yaml"))
    infrastructure_with_shelly = infrastructure.model_copy(
        update={
            "services": [
                *infrastructure.services,
                ServiceConfig(
                    id="shelly-kitchen",
                    name="Shelly cuisine",
                    type="shelly_telemetry",
                    node="infra-01",
                    metadata={
                        "power_entity_id": "sensor.shelly_kitchen_power",
                        "energy_entity_id": "sensor.shelly_kitchen_energy",
                        "maximum_age_seconds": 900,
                    },
                ),
                ServiceConfig(
                    id="shelly-garage",
                    name="Shelly garage",
                    type="shelly_telemetry",
                    node="infra-01",
                    metadata={
                        "power_entity_id": "sensor.shelly_garage_power",
                        "maximum_age_seconds": 900,
                    },
                ),
            ]
        }
    )
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(
        yaml.safe_dump(
            infrastructure.model_dump(
                mode="json",
                exclude_none=True,
            ),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    shelly_path = tmp_path / "shelly-telemetry.yaml"
    shelly_path.write_text(
        Path("config/plugins/shelly-telemetry.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    vision_client = FakeVisionClient()
    clock = FakeClock(
        current_time=datetime(2026, 7, 29, 8, 0, tzinfo=UTC),
    )
    shelly_check = FakeShellyTelemetryCheck()
    agent = build_production_agent(
        application_config_path=application_path,
        infrastructure_config_path=infrastructure_path,
        shelly_telemetry_config_path=shelly_path,
        vision_client=vision_client,
        clock=clock,
        shelly_telemetry_check=shelly_check,
    )

    assert agent.administration_runtime is not None
    repository = agent.administration_runtime.service.plugin_repository
    assert repository is not None
    initial = repository.read("home_assistant_telemetry")
    legacy_initial = repository.read("shelly_telemetry")
    assert initial.task_count == 0
    assert legacy_initial.id == "home_assistant_telemetry"
    assert legacy_initial.name == "Télémétrie Home Assistant"

    agent.apply_infrastructure_configuration(
        infrastructure_with_shelly,
        VisionInfrastructureMapper().to_payload(
            infrastructure_with_shelly,
        ),
    )

    after_architecture = repository.read("home_assistant_telemetry")
    assert after_architecture.task_count == 2

    updated = repository.write(
        "home_assistant_telemetry",
        {
            "enabled": True,
            "configuration": {
                **after_architecture.configuration,
                "interval_seconds": 120,
                "access_token": None,
            },
        },
    )

    assert updated.task_count == 2
    assert updated.interval_seconds == 120
    tasks = [
        task
        for task in agent.scheduler.list_tasks()
        if task.metadata.get("managed_by") == "home_assistant_telemetry"
    ]
    assert [task.arguments["service_id"] for task in tasks] == [
        "shelly-garage",
        "shelly-kitchen",
    ]
    assert {task.command for task in tasks} == {
        "home_assistant_telemetry.freshness",
    }

    execution = agent.scheduler.executor.execute(tasks[0], clock.now())

    assert execution.success is True
    assert execution.error is None
    assert shelly_check.devices == ["Shelly garage"]

    observations = [
        payload
        for operation, payload in vision_client.operations
        if operation == "observation"
    ]
    assert len(observations) == 1
    assert observations[0]["node_id"] == "infra-01"
    assert observations[0]["service_id"] == "shelly-garage"
    assert observations[0]["capability_id"] == "home_assistant.telemetry.freshness"
    assert observations[0]["status"] == "healthy"


def test_teleinformation_plugin_schedules_and_exports_linky_observation(
    tmp_path: Path,
) -> None:
    """A declared Linky service must run and reach Vision."""
    token_path = tmp_path / "management.token"
    token_path.write_text("test-token\n", encoding="utf-8")

    application_path = tmp_path / "shikamaru.yaml"
    application_path.write_text(
        f"""\
version: 1
agent:
  name: Shikamaru
  environment: test
vision:
  enabled: true
  observation_url: http://127.0.0.1:8000/api/observations
  infrastructure_url: http://127.0.0.1:8000/api/infrastructure
administration:
  enabled: true
  token_file: {token_path.as_posix()}
  dhcp:
    enabled: false
""",
        encoding="utf-8",
    )

    infrastructure = InfrastructureLoader().load(Path("config/infrastructure.yaml"))
    with_linky = infrastructure.model_copy(
        update={
            "services": [
                *infrastructure.services,
                ServiceConfig(
                    id="teleinformation-linky",
                    name="Téléinformation Linky",
                    type="teleinformation",
                    node="infra-01",
                    implementation="teleinfo2mqtt",
                    metadata={
                        "apparent_power_entity_id": (
                            "sensor.teleinfo_041964385922_sinsts"
                        ),
                        "tariff_entity_id": ("sensor.teleinfo_041964385922_ntarf"),
                        "blue_off_peak_entity_id": (
                            "sensor.teleinfo_041964385922_easf01"
                        ),
                        "blue_peak_entity_id": ("sensor.teleinfo_041964385922_easf02"),
                        "white_off_peak_entity_id": (
                            "sensor.teleinfo_041964385922_easf03"
                        ),
                        "white_peak_entity_id": ("sensor.teleinfo_041964385922_easf04"),
                        "red_off_peak_entity_id": (
                            "sensor.teleinfo_041964385922_easf05"
                        ),
                        "red_peak_entity_id": ("sensor.teleinfo_041964385922_easf06"),
                        "maximum_age_seconds": 180,
                    },
                ),
            ]
        }
    )
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(
        yaml.safe_dump(
            with_linky.model_dump(mode="json", exclude_none=True),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    plugin_path = tmp_path / "teleinformation.yaml"
    plugin_path.write_text(
        """\
enabled: true
timeout: 5.0
retries: 1
interval_seconds: 60
maximum_age_seconds: 180
home_assistant_url: http://ha-green.ohana.lan:8123
access_token: test-home-assistant-token
access_token_environment_variable: null
verify_tls: true
""",
        encoding="utf-8",
    )

    vision_client = FakeVisionClient()
    clock = FakeClock(current_time=datetime(2026, 7, 29, 8, 0, tzinfo=UTC))
    teleinformation_check = FakeTeleinformationCheck()
    agent = build_production_agent(
        application_config_path=application_path,
        infrastructure_config_path=infrastructure_path,
        teleinformation_config_path=plugin_path,
        vision_client=vision_client,
        clock=clock,
        teleinformation_check=teleinformation_check,
    )

    assert agent.administration_runtime is not None
    repository = agent.administration_runtime.service.plugin_repository
    assert repository is not None
    plugin_state = repository.read("teleinformation")
    assert plugin_state.task_count == 1
    assert plugin_state.interval_seconds == 60

    tasks = [
        task
        for task in agent.scheduler.list_tasks()
        if task.metadata.get("managed_by") == "teleinformation"
    ]
    assert len(tasks) == 1
    task = tasks[0]
    assert task.command == "teleinformation.freshness"
    assert task.arguments["tariff_entity_id"].endswith("_ntarf")
    assert task.arguments["red_peak_entity_id"].endswith("_easf06")

    execution = agent.scheduler.executor.execute(task, clock.now())

    assert execution.success is True
    assert execution.error is None
    assert teleinformation_check.meters == ["Téléinformation Linky"]
    observations = [
        payload
        for operation, payload in vision_client.operations
        if operation == "observation"
    ]
    assert len(observations) == 1
    observation = observations[0]
    assert observation["node_id"] == "infra-01"
    assert observation["service_id"] == "teleinformation-linky"
    assert observation["capability_id"] == "teleinformation.freshness"
    assert observation["status"] == "healthy"
    assert observation["metadata"]["tariff_color"] == "Bleue"
    assert observation["metadata"]["tariff_period"] == "HP"
    assert observation["metadata"]["active_index"]["value"] == 6931422.0
