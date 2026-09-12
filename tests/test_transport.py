from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ohana_agent.core.mqtt.transport import (
    MQTTLastWill,
    MQTTTransport,
    MQTTTransportNotConnectedError,
    MQTTTransportState,
)


class FakeNetworkBackend:
    def __init__(self) -> None:
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.published: list[dict[str, Any]] = []
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.fail_on_connect = False

    async def connect(self) -> None:
        self.connect_calls += 1

        if self.fail_on_connect:
            raise RuntimeError("Connection failed")

    async def disconnect(self) -> None:
        self.disconnect_calls += 1

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

    async def subscribe(self, topic: str) -> None:
        self.subscribed.append(topic)

    async def unsubscribe(self, topic: str) -> None:
        self.unsubscribed.append(topic)


def make_transport() -> tuple[MQTTTransport, FakeNetworkBackend]:
    backend = FakeNetworkBackend()
    transport = MQTTTransport(backend)

    return transport, backend


def test_transport_starts_disconnected() -> None:
    transport, _ = make_transport()

    assert transport.state == MQTTTransportState.DISCONNECTED
    assert transport.is_connected is False


def test_transport_accepts_last_will() -> None:
    backend = FakeNetworkBackend()
    last_will = MQTTLastWill(
        topic="ohana/agent/shikamaru/availability",
        payload='{"status": "offline"}',
        qos=1,
        retain=True,
    )

    transport = MQTTTransport(
        backend,
        last_will=last_will,
    )

    assert transport.last_will == last_will


def test_last_will_defaults() -> None:
    last_will = MQTTLastWill(
        topic="ohana/agent/shikamaru/availability",
        payload='{"status": "offline"}',
    )

    assert last_will.qos == 1
    assert last_will.retain is True


def test_connect_sets_connected_state() -> None:
    transport, backend = make_transport()

    asyncio.run(transport.connect())

    assert backend.connect_calls == 1
    assert transport.state == MQTTTransportState.CONNECTED
    assert transport.is_connected is True


def test_connect_is_idempotent_when_already_connected() -> None:
    transport, backend = make_transport()

    asyncio.run(transport.connect())
    asyncio.run(transport.connect())

    assert backend.connect_calls == 1
    assert transport.state == MQTTTransportState.CONNECTED


def test_connect_resets_state_when_backend_fails() -> None:
    transport, backend = make_transport()
    backend.fail_on_connect = True

    with pytest.raises(RuntimeError, match="Connection failed"):
        asyncio.run(transport.connect())

    assert transport.state == MQTTTransportState.DISCONNECTED
    assert transport.is_connected is False


def test_disconnect_sets_disconnected_state() -> None:
    transport, backend = make_transport()

    asyncio.run(transport.connect())
    asyncio.run(transport.disconnect())

    assert backend.disconnect_calls == 1
    assert transport.state == MQTTTransportState.DISCONNECTED
    assert transport.is_connected is False


def test_disconnect_is_safe_when_already_disconnected() -> None:
    transport, backend = make_transport()

    asyncio.run(transport.disconnect())

    assert backend.disconnect_calls == 0
    assert transport.state == MQTTTransportState.DISCONNECTED


def test_publish_delegates_to_backend() -> None:
    transport, backend = make_transport()

    asyncio.run(transport.connect())
    asyncio.run(
        transport.publish(
            "ohana/agent/shikamaru/status",
            '{"state": "running"}',
            qos=1,
            retain=True,
        )
    )

    assert backend.published == [
        {
            "topic": "ohana/agent/shikamaru/status",
            "payload": '{"state": "running"}',
            "qos": 1,
            "retain": True,
        }
    ]


def test_publish_requires_connection() -> None:
    transport, _ = make_transport()

    with pytest.raises(MQTTTransportNotConnectedError):
        asyncio.run(
            transport.publish(
                "ohana/agent/shikamaru/status",
                '{"state": "running"}',
                qos=1,
                retain=True,
            )
        )


def test_subscribe_delegates_to_backend() -> None:
    transport, backend = make_transport()

    asyncio.run(transport.connect())
    asyncio.run(transport.subscribe("ohana/agent/shikamaru/command"))

    assert backend.subscribed == ["ohana/agent/shikamaru/command"]


def test_subscribe_requires_connection() -> None:
    transport, _ = make_transport()

    with pytest.raises(MQTTTransportNotConnectedError):
        asyncio.run(transport.subscribe("ohana/agent/shikamaru/command"))


def test_unsubscribe_delegates_to_backend() -> None:
    transport, backend = make_transport()

    asyncio.run(transport.connect())
    asyncio.run(transport.unsubscribe("ohana/agent/shikamaru/command"))

    assert backend.unsubscribed == ["ohana/agent/shikamaru/command"]


def test_unsubscribe_requires_connection() -> None:
    transport, _ = make_transport()

    with pytest.raises(MQTTTransportNotConnectedError):
        asyncio.run(transport.unsubscribe("ohana/agent/shikamaru/command"))
