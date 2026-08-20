"""Tests for Home Assistant health publication through MQTT."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from configuration.infrastructure import InfrastructureConfig
from observer.observation import Observation
from observer.observation_status import ObservationStatus
from plugins.mqtt.home_assistant_publisher import MQTTHomeAssistantPublisher
from plugins.mqtt.host_health import HostHealthSnapshot
from plugins.mqtt.mqtt_config import (
    MQTTBrokerConfig,
    MQTTConfig,
    MQTTHomeAssistantConfig,
)


@dataclass
class FakePublishInfo:
    rc: int = 0


class FakePahoClient:
    def __init__(self) -> None:
        self.on_connect = None
        self.on_disconnect = None
        self.published: list[tuple[str, str, int, bool]] = []
        self.will: tuple[str, str, int, bool] | None = None
        self.connected_to: tuple[str, int, int] | None = None
        self.disconnected = False
        self.loop_stopped = False

    def username_pw_set(self, username: str, password: str | None) -> None:
        del username, password

    def tls_set(self, *, ca_certs: str | None) -> None:
        del ca_certs

    def tls_insecure_set(self, insecure: bool) -> None:
        del insecure

    def will_set(
        self,
        topic: str,
        *,
        payload: str,
        qos: int,
        retain: bool,
    ) -> None:
        self.will = (topic, payload, qos, retain)

    def connect(self, host: str, port: int, *, keepalive: int) -> int:
        self.connected_to = (host, port, keepalive)
        return 0

    def loop_start(self) -> None:
        assert self.on_connect is not None
        self.on_connect(self, None, None, 0, None)

    def publish(
        self,
        topic: str,
        payload: str,
        *,
        qos: int,
        retain: bool,
    ) -> FakePublishInfo:
        self.published.append((topic, payload, qos, retain))
        return FakePublishInfo()

    def disconnect(self) -> None:
        self.disconnected = True

    def loop_stop(self) -> None:
        self.loop_stopped = True


class FakeHostHealthMonitor:
    def __init__(self) -> None:
        self.collections = 0

    def collect(self) -> HostHealthSnapshot:
        self.collections += 1
        return HostHealthSnapshot(
            state="degraded",
            reasons=("memory_degraded",),
            updated_at="2026-08-10T15:00:00+00:00",
            hostname="infra-01",
            operating_system="Linux",
            kernel="6.12",
            cpu_count=4,
            cpu_percent=42.0,
            load_1m_per_cpu=0.5,
            memory_percent=86.0,
            memory_total_bytes=2_000_000,
            memory_available_bytes=1_000_000,
            swap_percent=2.0,
            swap_total_bytes=1_000_000,
            swap_used_bytes=20_000,
            disk_percent=30.0,
            disk_free_bytes=10_000_000,
            temperature_c=55.0,
            host_uptime_seconds=3600,
            agent_uptime_seconds=600,
            agent_restarts=0,
            failed_systemd_units=(),
            inactive_systemd_units=(),
        )


def make_infrastructure() -> InfrastructureConfig:
    return InfrastructureConfig.model_validate(
        {
            "infrastructure": {
                "id": "ohana-house",
                "name": "Ohana House",
            },
            "nodes": [
                {
                    "id": "infra-01",
                    "name": "INFRA-01",
                    "endpoint": {"type": "ip", "address": "192.168.1.10"},
                },
                {
                    "id": "zwave-01",
                    "name": "ZWAVE-01",
                    "endpoint": {"type": "ip", "address": "192.168.1.11"},
                },
            ],
            "services": [
                {
                    "id": "dns-primary",
                    "name": "DNS primaire",
                    "type": "dns",
                    "node": "infra-01",
                    "critical": True,
                },
                {
                    "id": "zwave-primary",
                    "name": "Z-Wave JS",
                    "type": "zwave",
                    "node": "zwave-01",
                    "critical": True,
                },
            ],
            "topology": {
                "devices": [
                    {
                        "id": "infra-01-device",
                        "label": "INFRA-01",
                        "kind": "server",
                        "node": "infra-01",
                    },
                    {
                        "id": "zwave-01-device",
                        "label": "ZWAVE-01",
                        "kind": "raspberry_pi",
                        "node": "zwave-01",
                    },
                ]
            },
        }
    )


def make_redundant_infrastructure() -> InfrastructureConfig:
    payload = make_infrastructure().model_dump(mode="json")
    payload["nodes"].append(
        {
            "id": "linky-01",
            "name": "LINKY-01",
            "endpoint": {"type": "ip", "address": "192.168.1.12"},
        }
    )
    payload["services"][0]["node"] = "zwave-01"
    payload["services"][0]["metadata"] = {"availability_group": "dns"}
    payload["services"].append(
        {
            "id": "dns-secondary",
            "name": "DNS secondaire",
            "type": "dns",
            "node": "linky-01",
            "critical": True,
            "metadata": {"availability_group": "dns"},
        }
    )
    payload["topology"]["devices"].append(
        {
            "id": "linky-01-device",
            "label": "LINKY-01",
            "kind": "raspberry_pi",
            "node": "linky-01",
        }
    )
    return InfrastructureConfig.model_validate(payload)


def make_legacy_redundant_infrastructure() -> InfrastructureConfig:
    payload = make_redundant_infrastructure().model_dump(mode="json")
    for service in payload["services"]:
        service["metadata"].pop("availability_group", None)
    return InfrastructureConfig.model_validate(payload)


def observation(
    *,
    node: str,
    service: str,
    capability: str,
    status: ObservationStatus,
    timestamp: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    message: str | None = None,
) -> Observation:
    return Observation(
        node=node,
        service=service,
        capability=capability,
        status=status,
        success=status is ObservationStatus.HEALTHY,
        message=message or f"{capability}: {status.value}",
        source=capability,
        timestamp=timestamp or datetime(2026, 7, 28, 14, 0, tzinfo=UTC),
        metadata=metadata or {},
    )


def test_health_summary_matches_vision_device_health_rules() -> None:
    config = MQTTConfig(
        home_assistant=MQTTHomeAssistantConfig(enabled=False),
    )
    publisher = MQTTHomeAssistantPublisher(
        config=config,
        infrastructure=make_infrastructure(),
        utc_now=lambda: datetime(2026, 7, 28, 14, 1, tzinfo=UTC),
        agent_version="1.8.1",
    )

    publisher.export(
        observation(
            node="infra-01",
            service="infra-01-device",
            capability="network.reachable",
            status=ObservationStatus.HEALTHY,
            metadata={
                "target_type": "device",
                "device_id": "infra-01-device",
            },
        )
    )
    publisher.export(
        observation(
            node="zwave-01",
            service="zwave-01-device",
            capability="network.reachable",
            status=ObservationStatus.HEALTHY,
            metadata={
                "target_type": "device",
                "device_id": "zwave-01-device",
            },
        )
    )
    publisher.export(
        observation(
            node="infra-01",
            service="dns-primary",
            capability="dns.resolve",
            status=ObservationStatus.HEALTHY,
        )
    )
    publisher.export(
        observation(
            node="zwave-01",
            service="zwave-primary",
            capability="zwave.status",
            status=ObservationStatus.UNHEALTHY,
        )
    )

    summary = publisher.build_summary()

    assert summary.score == 50.0
    assert summary.state == "critical"
    assert summary.active_alerts == 1
    assert summary.critical_incidents == 1
    assert summary.healthy_services == 1
    assert summary.unavailable_services == 1
    assert summary.critical_service == "zwave-primary"
    assert summary.critical_equipment == "ZWAVE-01"
    assert summary.critical_capability == "zwave.status"
    assert summary.affected_equipment == ("ZWAVE-01",)
    assert summary.affected_capabilities == ("zwave.status",)
    assert json.loads(summary.to_json())["alerts"] == [
        {
            "equipment": "ZWAVE-01",
            "node": "zwave-01",
            "service": "zwave-primary",
            "service_name": "Z-Wave JS",
            "capability": "zwave.status",
            "status": "unhealthy",
        }
    ]


def test_health_summary_aggregates_redundant_service_instances() -> None:
    now = datetime(2026, 8, 10, 14, 0, tzinfo=UTC)
    publisher = MQTTHomeAssistantPublisher(
        config=MQTTConfig(
            home_assistant=MQTTHomeAssistantConfig(enabled=False),
        ),
        infrastructure=make_legacy_redundant_infrastructure(),
        utc_now=lambda: now,
        agent_version="1.12.0",
    )
    publisher.export(
        observation(
            node="zwave-01",
            service="dns-primary",
            capability="dns.resolve",
            status=ObservationStatus.UNHEALTHY,
            timestamp=now,
        )
    )
    publisher.export(
        observation(
            node="linky-01",
            service="dns-secondary",
            capability="dns.resolve",
            status=ObservationStatus.HEALTHY,
            timestamp=now,
        )
    )
    publisher.export(
        observation(
            node="zwave-01",
            service="zwave-primary",
            capability="zwave.status",
            status=ObservationStatus.UNHEALTHY,
            timestamp=now + timedelta(seconds=1),
        )
    )

    summary = publisher.build_summary()

    assert summary.active_alerts == 2
    assert summary.healthy_services == 0
    assert summary.degraded_services == 1
    assert summary.unavailable_services == 1
    assert summary.state == "critical"
    assert summary.critical_incidents == 1
    assert summary.critical_capability == "zwave.status"


def test_partial_critical_dns_failure_only_degrades_logical_service() -> None:
    now = datetime(2026, 8, 10, 14, 0, tzinfo=UTC)
    publisher = MQTTHomeAssistantPublisher(
        config=MQTTConfig(
            home_assistant=MQTTHomeAssistantConfig(enabled=False),
        ),
        infrastructure=make_legacy_redundant_infrastructure(),
        utc_now=lambda: now,
        agent_version="1.12.3",
    )
    publisher.export(
        observation(
            node="zwave-01",
            service="dns-primary",
            capability="dns.resolve",
            status=ObservationStatus.UNHEALTHY,
            timestamp=now,
        )
    )
    publisher.export(
        observation(
            node="linky-01",
            service="dns-secondary",
            capability="dns.resolve",
            status=ObservationStatus.HEALTHY,
            timestamp=now,
        )
    )

    summary = publisher.build_summary()

    assert summary.active_alerts == 1
    assert summary.state == "degraded"
    assert summary.critical_incidents == 0
    assert summary.degraded_services == 1
    assert summary.unavailable_services == 0
    assert summary.critical_service is None
    assert summary.critical_equipment is None
    assert summary.critical_capability is None


def test_redundant_service_is_unavailable_when_all_instances_fail() -> None:
    publisher = MQTTHomeAssistantPublisher(
        config=MQTTConfig(
            home_assistant=MQTTHomeAssistantConfig(enabled=False),
        ),
        infrastructure=make_redundant_infrastructure(),
        agent_version="1.12.0",
    )
    for node, service in (
        ("zwave-01", "dns-primary"),
        ("linky-01", "dns-secondary"),
    ):
        publisher.export(
            observation(
                node=node,
                service=service,
                capability="dns.resolve",
                status=ObservationStatus.UNHEALTHY,
            )
        )

    summary = publisher.build_summary()

    assert summary.active_alerts == 2
    assert summary.degraded_services == 0
    assert summary.unavailable_services == 1


def test_health_summary_counts_stale_capabilities() -> None:
    now = datetime(2026, 7, 28, 14, 10, tzinfo=UTC)
    publisher = MQTTHomeAssistantPublisher(
        config=MQTTConfig(
            home_assistant=MQTTHomeAssistantConfig(
                enabled=False,
                heartbeat_seconds=60,
            )
        ),
        infrastructure=make_infrastructure(),
        utc_now=lambda: now,
        agent_version="1.8.1",
    )
    publisher.export(
        observation(
            node="infra-01",
            service="dns-primary",
            capability="dns.resolve",
            status=ObservationStatus.HEALTHY,
            timestamp=now - timedelta(seconds=181),
        )
    )

    assert publisher.build_summary().stale_capabilities == 1


def test_publisher_announces_discovery_summary_and_availability() -> None:
    fake_client = FakePahoClient()
    publisher = MQTTHomeAssistantPublisher(
        config=MQTTConfig(
            brokers=[
                MQTTBrokerConfig(
                    name="mqtt-primary",
                    address="192.168.1.247",
                )
            ],
            home_assistant=MQTTHomeAssistantConfig(
                enabled=True,
                discovery_enabled=True,
                discovery_prefix="homeassistant",
                topic_prefix="ohana",
                heartbeat_seconds=60,
            ),
        ),
        infrastructure=make_infrastructure(),
        client_factory=lambda client_id: fake_client,
        utc_now=lambda: datetime(2026, 7, 28, 14, 0, tzinfo=UTC),
        monotonic_clock=lambda: 10.0,
        agent_version="1.8.1",
    )

    publisher.publish_host_health(FakeHostHealthMonitor().collect())

    publisher.start()

    assert publisher.connected is True
    assert fake_client.connected_to == ("192.168.1.247", 1883, 60)
    assert fake_client.will == ("ohana/status", "offline", 1, True)

    topics = [topic for topic, *_ in fake_client.published]
    assert "homeassistant/sensor/ohana_health_score/config" in topics
    assert "homeassistant/binary_sensor/ohana_critical_incident/config" in topics
    assert "homeassistant/sensor/ohana_last_evaluation/config" in topics
    assert "ohana/status" in topics
    assert "ohana/health/summary" in topics
    assert "ohana/host/health" in topics
    summary_publications = [
        publication
        for publication in fake_client.published
        if publication[0] == "ohana/health/summary"
    ]
    assert summary_publications[-1][3] is True

    discovery_payload = next(
        json.loads(payload)
        for topic, payload, _qos, _retain in fake_client.published
        if topic == "homeassistant/sensor/ohana_health_score/config"
    )
    assert discovery_payload["device"]["name"] == "Ohana Platform"
    assert discovery_payload["device"]["sw_version"] == "1.8.1"
    assert discovery_payload["state_topic"] == "ohana/health/summary"

    obsolete_discovery = next(
        publication
        for publication in fake_client.published
        if publication[0] == "homeassistant/sensor/ohana_last_evaluation/config"
    )
    assert obsolete_discovery[1:] == ("", 1, True)

    health_state_discovery = next(
        json.loads(payload)
        for topic, payload, _qos, _retain in fake_client.published
        if topic == "homeassistant/sensor/ohana_health_state/config"
    )
    assert "critical_message" not in health_state_discovery["json_attributes_template"]

    active_alerts_discovery = next(
        json.loads(payload)
        for topic, payload, _qos, _retain in fake_client.published
        if topic == "homeassistant/sensor/ohana_active_alerts/config"
    )
    attributes_template = active_alerts_discovery["json_attributes_template"]
    assert "affected_equipment" in attributes_template
    assert "affected_capabilities" in attributes_template
    assert "alerts" in attributes_template

    host_health_discovery = next(
        json.loads(payload)
        for topic, payload, _qos, _retain in fake_client.published
        if topic == "homeassistant/sensor/ohana_host_health_state/config"
    )
    assert host_health_discovery["device"]["name"] == "Ohana Host"
    assert host_health_discovery["state_topic"] == "ohana/host/health"
    host_cpu_discovery = next(
        json.loads(payload)
        for topic, payload, _qos, _retain in fake_client.published
        if topic == "homeassistant/sensor/ohana_host_cpu_usage/config"
    )
    assert host_cpu_discovery["value_template"] == (
        "{{ value_json.cpu_percent if value_json.cpu_percent is not none "
        "else 'unknown' }}"
    )
    host_payload = next(
        json.loads(payload)
        for topic, payload, _qos, _retain in fake_client.published
        if topic == "ohana/host/health"
    )
    assert host_payload["state"] == "degraded"
    assert host_payload["reasons"] == ["memory_degraded"]

    publisher.stop()

    assert fake_client.disconnected is True
    assert fake_client.loop_stopped is True
    assert fake_client.published[-1][:2] == ("ohana/status", "offline")


def test_publisher_publishes_shared_host_health_snapshots() -> None:
    fake_client = FakePahoClient()
    host_health_monitor = FakeHostHealthMonitor()
    publisher = MQTTHomeAssistantPublisher(
        config=MQTTConfig(
            brokers=[
                MQTTBrokerConfig(
                    name="mqtt-primary",
                    address="192.168.1.247",
                )
            ],
            home_assistant=MQTTHomeAssistantConfig(
                enabled=True,
                heartbeat_seconds=60,
            ),
        ),
        infrastructure=make_infrastructure(),
        client_factory=lambda _client_id: fake_client,
    )
    publisher.start()

    publisher.publish_host_health(host_health_monitor.collect())
    publisher.publish_host_health(host_health_monitor.collect())

    host_publications = [
        publication
        for publication in fake_client.published
        if publication[0] == "ohana/host/health"
    ]
    assert host_health_monitor.collections == 2
    assert len(host_publications) == 2
    assert all(publication[3] is True for publication in host_publications)


def test_publisher_ignores_timestamp_and_message_only_changes() -> None:
    now = datetime(2026, 7, 28, 14, 0, tzinfo=UTC)
    fake_client = FakePahoClient()
    publisher = MQTTHomeAssistantPublisher(
        config=MQTTConfig(
            brokers=[
                MQTTBrokerConfig(
                    name="mqtt-primary",
                    address="192.168.1.247",
                )
            ],
            home_assistant=MQTTHomeAssistantConfig(enabled=True),
        ),
        infrastructure=make_infrastructure(),
        client_factory=lambda client_id: fake_client,
        utc_now=lambda: now,
        agent_version="1.11.10",
    )
    publisher.start()
    publisher.export(
        observation(
            node="infra-01",
            service="dns-primary",
            capability="dns.resolve",
            status=ObservationStatus.UNHEALTHY,
            timestamp=now,
            message="First DNS error.",
        )
    )
    publications_after_state_change = len(
        [
            publication
            for publication in fake_client.published
            if publication[0] == "ohana/health/summary"
        ]
    )

    publisher.export(
        observation(
            node="infra-01",
            service="dns-primary",
            capability="dns.resolve",
            status=ObservationStatus.UNHEALTHY,
            timestamp=now + timedelta(seconds=1),
            message="A newer DNS error detail.",
        )
    )

    summary_publications = [
        publication
        for publication in fake_client.published
        if publication[0] == "ohana/health/summary"
    ]
    assert len(summary_publications) == publications_after_state_change


def test_publisher_republishes_a_meaningful_health_change() -> None:
    now = datetime(2026, 7, 28, 14, 0, tzinfo=UTC)
    fake_client = FakePahoClient()
    publisher = MQTTHomeAssistantPublisher(
        config=MQTTConfig(
            brokers=[
                MQTTBrokerConfig(
                    name="mqtt-primary",
                    address="192.168.1.247",
                )
            ],
            home_assistant=MQTTHomeAssistantConfig(enabled=True),
        ),
        infrastructure=make_infrastructure(),
        client_factory=lambda client_id: fake_client,
        utc_now=lambda: now,
        agent_version="1.11.10",
    )
    publisher.start()
    publisher.export(
        observation(
            node="infra-01",
            service="dns-primary",
            capability="dns.resolve",
            status=ObservationStatus.HEALTHY,
            timestamp=now,
        )
    )
    publications_before_incident = len(
        [
            publication
            for publication in fake_client.published
            if publication[0] == "ohana/health/summary"
        ]
    )

    publisher.export(
        observation(
            node="infra-01",
            service="dns-primary",
            capability="dns.resolve",
            status=ObservationStatus.UNHEALTHY,
            timestamp=now + timedelta(seconds=1),
        )
    )

    summary_publications = [
        publication
        for publication in fake_client.published
        if publication[0] == "ohana/health/summary"
    ]
    assert len(summary_publications) == publications_before_incident + 1
    assert json.loads(summary_publications[-1][1])["state"] == "critical"


def test_publisher_republishes_when_alert_identity_changes_at_same_count() -> None:
    now = datetime(2026, 7, 28, 14, 0, tzinfo=UTC)
    fake_client = FakePahoClient()
    publisher = MQTTHomeAssistantPublisher(
        config=MQTTConfig(
            brokers=[
                MQTTBrokerConfig(
                    name="mqtt-primary",
                    address="192.168.1.247",
                )
            ],
            home_assistant=MQTTHomeAssistantConfig(enabled=True),
        ),
        infrastructure=make_infrastructure(),
        client_factory=lambda client_id: fake_client,
        utc_now=lambda: now,
        agent_version="1.11.10",
    )
    publisher.start()
    publisher.export(
        observation(
            node="infra-01",
            service="dns-primary",
            capability="dns.resolve",
            status=ObservationStatus.DEGRADED,
            timestamp=now,
        )
    )
    publications_before_identity_change = len(
        [
            publication
            for publication in fake_client.published
            if publication[0] == "ohana/health/summary"
        ]
    )

    publisher.export(
        observation(
            node="infra-01",
            service="dns-primary",
            capability="dns.resolve",
            status=ObservationStatus.HEALTHY,
            timestamp=now + timedelta(seconds=1),
        )
    )
    publisher.export(
        observation(
            node="zwave-01",
            service="zwave-primary",
            capability="zwave.status",
            status=ObservationStatus.DEGRADED,
            timestamp=now + timedelta(seconds=1),
        )
    )

    summary_publications = [
        publication
        for publication in fake_client.published
        if publication[0] == "ohana/health/summary"
    ]
    assert len(summary_publications) == publications_before_identity_change + 2
    summary = json.loads(summary_publications[-1][1])
    assert summary["active_alerts"] == 1
    assert summary["affected_equipment"] == ["ZWAVE-01"]
    assert summary["affected_capabilities"] == ["zwave.status"]
    assert summary["alerts"] == [
        {
            "equipment": "ZWAVE-01",
            "node": "zwave-01",
            "service": "zwave-primary",
            "service_name": "Z-Wave JS",
            "capability": "zwave.status",
            "status": "degraded",
        }
    ]


def test_infrastructure_reconfiguration_keeps_mqtt_availability_online() -> None:
    """Infrastructure changes must not create a false MQTT outage."""
    fake_client = FakePahoClient()
    config = MQTTConfig(
        brokers=[
            MQTTBrokerConfig(
                name="mqtt-primary",
                address="192.168.1.247",
            )
        ],
        home_assistant=MQTTHomeAssistantConfig(
            enabled=True,
            topic_prefix="ohana",
        ),
    )
    publisher = MQTTHomeAssistantPublisher(
        config=config,
        infrastructure=make_infrastructure(),
        client_factory=lambda client_id: fake_client,
        agent_version="1.11.3",
    )
    publisher.start()
    publications_before = len(fake_client.published)

    publisher.reconfigure(
        config,
        infrastructure=make_infrastructure(),
    )

    new_publications = fake_client.published[publications_before:]
    assert publisher.connected is True
    assert fake_client.disconnected is False
    assert fake_client.loop_stopped is False
    assert not any(
        topic == "ohana/status" and payload == "offline"
        for topic, payload, _qos, _retain in new_publications
    )
    assert [topic for topic, *_ in new_publications] == ["ohana/health/summary"]
    assert new_publications[0][3] is True
