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


def observation(
    *,
    node: str,
    service: str,
    capability: str,
    status: ObservationStatus,
    timestamp: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> Observation:
    return Observation(
        node=node,
        service=service,
        capability=capability,
        status=status,
        success=status is ObservationStatus.HEALTHY,
        message=f"{capability}: {status.value}",
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

    publisher.start()

    assert publisher.connected is True
    assert fake_client.connected_to == ("192.168.1.247", 1883, 60)
    assert fake_client.will == ("ohana/status", "offline", 1, True)

    topics = [topic for topic, *_ in fake_client.published]
    assert "homeassistant/sensor/ohana_health_score/config" in topics
    assert "homeassistant/binary_sensor/ohana_critical_incident/config" in topics
    assert "ohana/status" in topics
    assert "ohana/health/summary" in topics
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

    publisher.stop()

    assert fake_client.disconnected is True
    assert fake_client.loop_stopped is True
    assert fake_client.published[-1][:2] == ("ohana/status", "offline")


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
