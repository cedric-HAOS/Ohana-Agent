from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from ohana_agent.core.mqtt.client import (
    MQTTClient,
    MQTTClientNotConnectedError,
    MQTTConnectionState,
)


@dataclass
class DummyMQTTConfig:
    enabled: bool = True
    qos: int = 1
    retain: bool = False


class FakeTransport:
    def __init__(self) -> None:
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.fail_on_connect = False

    async def connect(self) -> None:
        self.connect_calls += 1

        if self.fail_on_connect:
            raise RuntimeError("Connection failed")

    async def disconnect(self) -> None:
        self.disconnect_calls += 1


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish(
        self,
        topic: str,
        payload: object,
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


class FakeSubscriber:
    def __init__(self) -> None:
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    async def subscribe(self, topic: str) -> None:
        self.subscribed.append(topic)

    async def unsubscribe(self, topic: str) -> None:
        self.unsubscribed.append(topic)


def make_client(
    config: DummyMQTTConfig | None = None,
) -> tuple[MQTTClient, FakeTransport, FakePublisher, FakeSubscriber]:
    transport = FakeTransport()
    publisher = FakePublisher()
    subscriber = FakeSubscriber()

    client = MQTTClient(
        config=config or DummyMQTTConfig(),
        transport=transport,
        publisher=publisher,
        subscriber=subscriber,
    )

    return client, transport, publisher, subscriber


def test_mqtt_client_starts_disconnected() -> None:
    client, _, _, _ = make_client()

    assert client.state == MQTTConnectionState.DISCONNECTED
    assert client.is_connected is False


def test_connect_sets_connected_state() -> None:
    client, transport, _, _ = make_client()

    asyncio.run(client.connect())

    assert transport.connect_calls == 1
    assert client.state == MQTTConnectionState.CONNECTED
    assert client.is_connected is True


def test_connect_is_idempotent_when_already_connected() -> None:
    client, transport, _, _ = make_client()

    asyncio.run(client.connect())
    asyncio.run(client.connect())

    assert transport.connect_calls == 1
    assert client.state == MQTTConnectionState.CONNECTED


def test_connect_does_nothing_when_mqtt_is_disabled() -> None:
    client, transport, _, _ = make_client(DummyMQTTConfig(enabled=False))

    asyncio.run(client.connect())

    assert transport.connect_calls == 0
    assert client.state == MQTTConnectionState.DISCONNECTED


def test_connect_restores_existing_subscriptions() -> None:
    client, _, _, subscriber = make_client()

    asyncio.run(client.subscribe("ohana/agent/shikamaru/command"))
    asyncio.run(client.connect())

    assert subscriber.subscribed == ["ohana/agent/shikamaru/command"]


def test_connect_resets_state_when_transport_fails() -> None:
    client, transport, _, _ = make_client()
    transport.fail_on_connect = True

    with pytest.raises(RuntimeError, match="Connection failed"):
        asyncio.run(client.connect())

    assert client.state == MQTTConnectionState.DISCONNECTED
    assert client.is_connected is False


def test_disconnect_sets_disconnected_state() -> None:
    client, transport, _, _ = make_client()

    asyncio.run(client.connect())
    asyncio.run(client.disconnect())

    assert transport.disconnect_calls == 1
    assert client.state == MQTTConnectionState.DISCONNECTED
    assert client.is_connected is False


def test_disconnect_is_safe_when_already_disconnected() -> None:
    client, transport, _, _ = make_client()

    asyncio.run(client.disconnect())

    assert transport.disconnect_calls == 0
    assert client.state == MQTTConnectionState.DISCONNECTED


def test_publish_delegates_to_publisher() -> None:
    client, _, publisher, _ = make_client(DummyMQTTConfig(qos=1, retain=True))

    asyncio.run(client.connect())
    asyncio.run(
        client.publish(
            "ohana/agent/shikamaru/status",
            {"state": "running"},
        )
    )

    assert publisher.published == [
        {
            "topic": "ohana/agent/shikamaru/status",
            "payload": {"state": "running"},
            "qos": 1,
            "retain": True,
        }
    ]


def test_publish_requires_connection() -> None:
    client, _, _, _ = make_client()

    with pytest.raises(MQTTClientNotConnectedError):
        asyncio.run(
            client.publish(
                "ohana/agent/shikamaru/status",
                {"state": "running"},
            )
        )


def test_subscribe_stores_topic_when_disconnected() -> None:
    client, _, _, subscriber = make_client()

    asyncio.run(client.subscribe("ohana/agent/shikamaru/command"))

    assert subscriber.subscribed == []


def test_subscribe_delegates_when_connected() -> None:
    client, _, _, subscriber = make_client()

    asyncio.run(client.connect())
    asyncio.run(client.subscribe("ohana/agent/shikamaru/command"))

    assert subscriber.subscribed == ["ohana/agent/shikamaru/command"]


def test_unsubscribe_removes_topic_and_delegates_when_connected() -> None:
    client, _, _, subscriber = make_client()

    asyncio.run(client.subscribe("ohana/agent/shikamaru/command"))
    asyncio.run(client.connect())
    asyncio.run(client.unsubscribe("ohana/agent/shikamaru/command"))

    assert subscriber.unsubscribed == ["ohana/agent/shikamaru/command"]
