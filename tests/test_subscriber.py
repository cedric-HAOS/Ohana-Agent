from __future__ import annotations

import asyncio

import pytest

from ohana_agent.core.mqtt.subscriber import MQTTMessageReceivedEvent, MQTTSubscriber


class FakeBackendSubscriber:
    def __init__(self) -> None:
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    async def subscribe(self, topic: str) -> None:
        self.subscribed.append(topic)

    async def unsubscribe(self, topic: str) -> None:
        self.unsubscribed.append(topic)


class FakeDispatcher:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def dispatch(self, event: object) -> None:
        self.events.append(event)


def make_subscriber() -> tuple[
    MQTTSubscriber,
    FakeBackendSubscriber,
    FakeDispatcher,
]:
    backend = FakeBackendSubscriber()
    dispatcher = FakeDispatcher()

    subscriber = MQTTSubscriber(
        backend=backend,
        dispatcher=dispatcher,
    )

    return subscriber, backend, dispatcher


def test_subscribe_delegates_to_backend() -> None:
    subscriber, backend, _ = make_subscriber()

    asyncio.run(subscriber.subscribe("ohana/agent/shikamaru/command"))

    assert backend.subscribed == ["ohana/agent/shikamaru/command"]


def test_unsubscribe_delegates_to_backend() -> None:
    subscriber, backend, _ = make_subscriber()

    asyncio.run(subscriber.unsubscribe("ohana/agent/shikamaru/command"))

    assert backend.unsubscribed == ["ohana/agent/shikamaru/command"]


def test_deserialize_json_string_payload() -> None:
    subscriber, _, _ = make_subscriber()

    payload = subscriber.deserialize('{"command": "status"}')

    assert payload == {"command": "status"}


def test_deserialize_json_bytes_payload() -> None:
    subscriber, _, _ = make_subscriber()

    payload = subscriber.deserialize(b'{"command": "status"}')

    assert payload == {"command": "status"}


def test_deserialize_json_list_payload() -> None:
    subscriber, _, _ = make_subscriber()

    payload = subscriber.deserialize('[{"name": "mqtt"}]')

    assert payload == [{"name": "mqtt"}]


def test_deserialize_json_string_value_payload() -> None:
    subscriber, _, _ = make_subscriber()

    payload = subscriber.deserialize('"online"')

    assert payload == "online"


def test_deserialize_invalid_json_raises_error() -> None:
    subscriber, _, _ = make_subscriber()

    with pytest.raises(ValueError):
        subscriber.deserialize("not-json")


def test_handle_message_dispatches_event() -> None:
    subscriber, _, dispatcher = make_subscriber()

    asyncio.run(
        subscriber.handle_message(
            "ohana/agent/shikamaru/command",
            '{"command": "status"}',
        )
    )

    assert dispatcher.events == [
        MQTTMessageReceivedEvent(
            topic="ohana/agent/shikamaru/command",
            payload={"command": "status"},
        )
    ]


def test_handle_message_accepts_bytes_payload() -> None:
    subscriber, _, dispatcher = make_subscriber()

    asyncio.run(
        subscriber.handle_message(
            "ohana/agent/shikamaru/command",
            b'{"command": "restart"}',
        )
    )

    assert dispatcher.events == [
        MQTTMessageReceivedEvent(
            topic="ohana/agent/shikamaru/command",
            payload={"command": "restart"},
        )
    ]


def test_handle_message_does_not_dispatch_invalid_json() -> None:
    subscriber, _, dispatcher = make_subscriber()

    with pytest.raises(ValueError):
        asyncio.run(
            subscriber.handle_message(
                "ohana/agent/shikamaru/command",
                "not-json",
            )
        )

    assert dispatcher.events == []
