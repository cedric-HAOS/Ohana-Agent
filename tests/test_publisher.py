from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ohana_agent.core.mqtt.publisher import MQTTPublisher


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"


@dataclass
class StatusMessage:
    agent: str
    state: str
    health: HealthStatus


class FakeBackendPublisher:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish(
        self,
        topic: str,
        payload: str,
        *,
        qos: int,
        retain: bool,
    ) -> None:
        self.published.append(
            {
                "topic": topic,
                "payload": payload,
                "qos": qos,
                "retain": retain,
            }
        )


def test_serialize_dict_payload() -> None:
    backend = FakeBackendPublisher()
    publisher = MQTTPublisher(backend)

    serialized = publisher.serialize({"state": "running"})

    assert json.loads(serialized) == {"state": "running"}


def test_serialize_keeps_unicode_characters() -> None:
    backend = FakeBackendPublisher()
    publisher = MQTTPublisher(backend)

    serialized = publisher.serialize({"message": "Démarrage réussi"})

    assert "Démarrage réussi" in serialized


def test_serialize_dataclass_payload() -> None:
    backend = FakeBackendPublisher()
    publisher = MQTTPublisher(backend)

    serialized = publisher.serialize(
        StatusMessage(
            agent="shikamaru",
            state="running",
            health=HealthStatus.HEALTHY,
        )
    )

    assert json.loads(serialized) == {
        "agent": "shikamaru",
        "state": "running",
        "health": "healthy",
    }


def test_serialize_enum_payload() -> None:
    backend = FakeBackendPublisher()
    publisher = MQTTPublisher(backend)

    serialized = publisher.serialize(HealthStatus.DEGRADED)

    assert json.loads(serialized) == "degraded"


def test_serialize_datetime_payload() -> None:
    backend = FakeBackendPublisher()
    publisher = MQTTPublisher(backend)

    value = datetime(2026, 7, 8, 10, 30, tzinfo=UTC)

    serialized = publisher.serialize({"created_at": value})

    assert json.loads(serialized) == {"created_at": "2026-07-08T10:30:00+00:00"}


def test_serialize_nested_payload() -> None:
    backend = FakeBackendPublisher()
    publisher = MQTTPublisher(backend)

    serialized = publisher.serialize(
        {
            "agent": "shikamaru",
            "checks": [
                {"name": "mqtt", "status": HealthStatus.HEALTHY},
                {"name": "dispatcher", "status": HealthStatus.DEGRADED},
            ],
        }
    )

    assert json.loads(serialized) == {
        "agent": "shikamaru",
        "checks": [
            {"name": "mqtt", "status": "healthy"},
            {"name": "dispatcher", "status": "degraded"},
        ],
    }


def test_publish_delegates_serialized_payload_to_backend() -> None:
    backend = FakeBackendPublisher()
    publisher = MQTTPublisher(backend)

    asyncio.run(
        publisher.publish(
            "ohana/agent/shikamaru/status",
            {"state": "running"},
            qos=1,
            retain=True,
        )
    )

    assert len(backend.published) == 1

    published = backend.published[0]

    assert published["topic"] == "ohana/agent/shikamaru/status"
    assert published["qos"] == 1
    assert published["retain"] is True
    assert json.loads(published["payload"]) == {"state": "running"}


def test_publish_uses_default_qos_and_retain() -> None:
    backend = FakeBackendPublisher()
    publisher = MQTTPublisher(backend)

    asyncio.run(
        publisher.publish(
            "ohana/agent/shikamaru/events",
            {"event": "started"},
        )
    )

    assert backend.published[0]["qos"] == 0
    assert backend.published[0]["retain"] is False
