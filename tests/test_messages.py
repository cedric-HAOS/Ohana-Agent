from __future__ import annotations

from ohana_agent.core.mqtt.messages import (
    MQTTAvailabilityMessage,
    MQTTAvailabilityStatus,
    MQTTCommandMessage,
    MQTTEventMessage,
    MQTTHealthStatus,
    MQTTStatusMessage,
)


def test_availability_message_online_to_dict() -> None:
    message = MQTTAvailabilityMessage(
        status=MQTTAvailabilityStatus.ONLINE,
    )

    assert message.to_dict() == {
        "status": "online",
    }


def test_availability_message_offline_to_dict() -> None:
    message = MQTTAvailabilityMessage(
        status=MQTTAvailabilityStatus.OFFLINE,
    )

    assert message.to_dict() == {
        "status": "offline",
    }


def test_status_message_to_dict() -> None:
    message = MQTTStatusMessage(
        agent="shikamaru",
        state="running",
        health=MQTTHealthStatus.HEALTHY,
        uptime=1532,
        version="0.3.0",
        timestamp="2026-07-08T10:30:00+00:00",
    )

    assert message.to_dict() == {
        "agent": "shikamaru",
        "state": "running",
        "health": "healthy",
        "uptime": 1532,
        "version": "0.3.0",
        "timestamp": "2026-07-08T10:30:00+00:00",
    }


def test_status_message_create_adds_timestamp() -> None:
    message = MQTTStatusMessage.create(
        agent="shikamaru",
        state="running",
        health=MQTTHealthStatus.HEALTHY,
        uptime=1532,
        version="0.3.0",
    )

    assert message.agent == "shikamaru"
    assert message.state == "running"
    assert message.health == MQTTHealthStatus.HEALTHY
    assert message.uptime == 1532
    assert message.version == "0.3.0"
    assert message.timestamp.endswith("+00:00")


def test_status_message_supports_degraded_health() -> None:
    message = MQTTStatusMessage(
        agent="shikamaru",
        state="running",
        health=MQTTHealthStatus.DEGRADED,
        uptime=1532,
        version="0.3.0",
        timestamp="2026-07-08T10:30:00+00:00",
    )

    assert message.to_dict()["health"] == "degraded"


def test_status_message_supports_unhealthy_health() -> None:
    message = MQTTStatusMessage(
        agent="shikamaru",
        state="error",
        health=MQTTHealthStatus.UNHEALTHY,
        uptime=1532,
        version="0.3.0",
        timestamp="2026-07-08T10:30:00+00:00",
    )

    assert message.to_dict()["health"] == "unhealthy"


def test_command_message_minimal_to_dict() -> None:
    message = MQTTCommandMessage(command="status")

    assert message.to_dict() == {
        "command": "status",
    }


def test_command_message_with_correlation_id_to_dict() -> None:
    message = MQTTCommandMessage(
        command="restart",
        correlation_id="abc-123",
    )

    assert message.to_dict() == {
        "command": "restart",
        "correlation_id": "abc-123",
    }


def test_command_message_with_payload_to_dict() -> None:
    message = MQTTCommandMessage(
        command="set_mode",
        payload={"mode": "maintenance"},
    )

    assert message.to_dict() == {
        "command": "set_mode",
        "payload": {"mode": "maintenance"},
    }


def test_command_message_complete_to_dict() -> None:
    message = MQTTCommandMessage(
        command="set_mode",
        correlation_id="abc-123",
        payload={"mode": "maintenance"},
    )

    assert message.to_dict() == {
        "command": "set_mode",
        "correlation_id": "abc-123",
        "payload": {"mode": "maintenance"},
    }


def test_event_message_to_dict() -> None:
    message = MQTTEventMessage(
        event_type="mqtt.connected",
        payload={"client_id": "shikamaru"},
        timestamp="2026-07-08T10:30:00+00:00",
    )

    assert message.to_dict() == {
        "event_type": "mqtt.connected",
        "payload": {"client_id": "shikamaru"},
        "timestamp": "2026-07-08T10:30:00+00:00",
    }


def test_event_message_create_adds_timestamp() -> None:
    message = MQTTEventMessage.create(
        event_type="mqtt.connected",
        payload={"client_id": "shikamaru"},
    )

    assert message.event_type == "mqtt.connected"
    assert message.payload == {"client_id": "shikamaru"}
    assert message.timestamp.endswith("+00:00")
