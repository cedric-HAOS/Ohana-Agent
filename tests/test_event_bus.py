"""Tests for the Shikamaru event bus."""

import pytest

from ohana_agent.core.events import EventBus, EventHandlerNotFoundError


class DummyEvent:
    def __init__(self, value: str) -> None:
        self.value = value


class AnotherEvent:
    pass


def test_event_bus_publish_to_subscriber() -> None:
    bus = EventBus()
    received: list[DummyEvent] = []

    def handler(event: DummyEvent) -> None:
        received.append(event)

    event = DummyEvent("hello")

    bus.subscribe(DummyEvent, handler)
    bus.publish(event)

    assert received == [event]


def test_event_bus_publish_without_subscriber_does_nothing() -> None:
    bus = EventBus()

    bus.publish(DummyEvent("hello"))


def test_event_bus_publish_to_multiple_subscribers() -> None:
    bus = EventBus()
    received_a: list[DummyEvent] = []
    received_b: list[DummyEvent] = []

    def handler_a(event: DummyEvent) -> None:
        received_a.append(event)

    def handler_b(event: DummyEvent) -> None:
        received_b.append(event)

    event = DummyEvent("hello")

    bus.subscribe(DummyEvent, handler_a)
    bus.subscribe(DummyEvent, handler_b)
    bus.publish(event)

    assert received_a == [event]
    assert received_b == [event]


def test_event_bus_does_not_publish_to_other_event_type() -> None:
    bus = EventBus()
    received: list[DummyEvent] = []

    def handler(event: DummyEvent) -> None:
        received.append(event)

    bus.subscribe(DummyEvent, handler)
    bus.publish(AnotherEvent())

    assert received == []


def test_event_bus_unsubscribe_removes_handler() -> None:
    bus = EventBus()
    received: list[DummyEvent] = []

    def handler(event: DummyEvent) -> None:
        received.append(event)

    bus.subscribe(DummyEvent, handler)
    bus.unsubscribe(DummyEvent, handler)
    bus.publish(DummyEvent("hello"))

    assert received == []


def test_event_bus_unsubscribe_unknown_handler_raises_error() -> None:
    bus = EventBus()

    def handler(event: DummyEvent) -> None:
        _ = event

    with pytest.raises(EventHandlerNotFoundError):
        bus.unsubscribe(DummyEvent, handler)


def test_event_bus_handler_can_unsubscribe_during_publish() -> None:
    bus = EventBus()
    received: list[DummyEvent] = []

    def handler(event: DummyEvent) -> None:
        received.append(event)
        bus.unsubscribe(DummyEvent, handler)

    first_event = DummyEvent("first")
    second_event = DummyEvent("second")

    bus.subscribe(DummyEvent, handler)

    bus.publish(first_event)
    bus.publish(second_event)

    assert received == [first_event]
