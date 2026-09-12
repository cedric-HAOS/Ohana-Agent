from __future__ import annotations

import asyncio
from typing import Any

from ohana_agent.core.mqtt.heartbeat import MQTTHeartbeatConfig, MQTTHeartbeatService
from ohana_agent.core.mqtt.messages import MQTTAvailabilityStatus, MQTTHealthStatus


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish(
        self,
        topic: str,
        payload: object,
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        self.published.append(
            {
                "topic": topic,
                "payload": payload,
                "qos": qos,
                "retain": retain,
            }
        )


def make_service(
    config: MQTTHeartbeatConfig | None = None,
) -> tuple[MQTTHeartbeatService, FakePublisher]:
    publisher = FakePublisher()
    service = MQTTHeartbeatService(
        config=config or MQTTHeartbeatConfig(),
        publisher=publisher,
    )

    return service, publisher


def test_status_topic_uses_base_topic() -> None:
    service, _ = make_service()

    assert service.status_topic == "ohana/agent/shikamaru/status"


def test_availability_topic_uses_base_topic() -> None:
    service, _ = make_service()

    assert service.availability_topic == "ohana/agent/shikamaru/availability"


def test_build_status_message() -> None:
    service, _ = make_service(
        MQTTHeartbeatConfig(
            agent_name="shikamaru",
            version="0.3.0",
        )
    )

    message = service.build_status_message(
        state="running",
        health=MQTTHealthStatus.HEALTHY,
        uptime_seconds=1532,
    )

    assert message.agent == "shikamaru"
    assert message.state == "running"
    assert message.health == MQTTHealthStatus.HEALTHY
    assert message.uptime == 1532
    assert message.version == "0.3.0"
    assert message.timestamp.endswith("+00:00")


def test_build_availability_message_online() -> None:
    service, _ = make_service()

    message = service.build_availability_message(
        MQTTAvailabilityStatus.ONLINE,
    )

    assert message.to_dict() == {
        "status": "online",
    }


def test_build_availability_message_offline() -> None:
    service, _ = make_service()

    message = service.build_availability_message(
        MQTTAvailabilityStatus.OFFLINE,
    )

    assert message.to_dict() == {
        "status": "offline",
    }


def test_publish_heartbeat_once() -> None:
    service, publisher = make_service()

    asyncio.run(
        service.publish_heartbeat_once(
            state="running",
            health=MQTTHealthStatus.HEALTHY,
            uptime_seconds=1532,
        )
    )

    assert len(publisher.published) == 1

    published = publisher.published[0]

    assert published["topic"] == "ohana/agent/shikamaru/status"
    assert published["qos"] == 1
    assert published["retain"] is False
    assert published["payload"]["agent"] == "shikamaru"
    assert published["payload"]["state"] == "running"
    assert published["payload"]["health"] == "healthy"
    assert published["payload"]["uptime"] == 1532
    assert published["payload"]["version"] == "0.3.0"
    assert "timestamp" in published["payload"]


def test_publish_online() -> None:
    service, publisher = make_service()

    asyncio.run(service.publish_online())

    assert publisher.published == [
        {
            "topic": "ohana/agent/shikamaru/availability",
            "payload": {"status": "online"},
            "qos": 1,
            "retain": True,
        }
    ]


def test_publish_offline() -> None:
    service, publisher = make_service()

    asyncio.run(service.publish_offline())

    assert publisher.published == [
        {
            "topic": "ohana/agent/shikamaru/availability",
            "payload": {"status": "offline"},
            "qos": 1,
            "retain": True,
        }
    ]


def test_custom_config_is_used() -> None:
    service, publisher = make_service(
        MQTTHeartbeatConfig(
            agent_name="custom-agent",
            base_topic="custom/base",
            version="9.9.9",
            qos=2,
            retain=True,
        )
    )

    asyncio.run(
        service.publish_heartbeat_once(
            state="ready",
            health=MQTTHealthStatus.DEGRADED,
            uptime_seconds=42,
        )
    )

    published = publisher.published[0]

    assert published["topic"] == "custom/base/status"
    assert published["qos"] == 2
    assert published["retain"] is True
    assert published["payload"]["agent"] == "custom-agent"
    assert published["payload"]["health"] == "degraded"
    assert published["payload"]["version"] == "9.9.9"
