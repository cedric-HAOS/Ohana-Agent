"""Tests for the Shikamaru event bus."""

import pytest

from ohana_agent.core.events import EventBus, EventHandlerNotFoundError


class DummyEvent:
    """Dummy event used for event bus tests."""

    def __init__(self, value: str) -> None:
        self.value = value


class AnotherEvent:
    """Another dummy event used for event bus tests."""


def test_subscribe_and_publish_event() -> None:
    """A subscribed handler receives published events."""
    bus = EventBus()
    received: list[DummyEvent] = []

    def handler(event: DummyEvent) -> None:
        received.append(event)

    event = DummyEvent("hello")

    bus.subscribe(DummyEvent, handler)
    bus.publish(event)

    assert received == [event]


def test_publish_without_subscribers_does_nothing() -> None:
    """Publishing an event without subscribers does not fail."""
    bus = EventBus()

    bus.publish(DummyEvent("hello"))


def test_multiple_handlers_receive_same_event() -> None:
    """Multiple handlers subscribed to the same event receive it."""
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


def test_handler_for_other_event_type_is_not_called() -> None:
    """A handler only receives events of its subscribed type."""
    bus = EventBus()
    received: list[DummyEvent] = []

    def handler(event: DummyEvent) -> None:
        received.append(event)

    bus.subscribe(DummyEvent, handler)
    bus.publish(AnotherEvent())

    assert received == []


def test_unsubscribe_handler() -> None:
    """An unsubscribed handler no longer receives events."""
    bus = EventBus()
    received: list[DummyEvent] = []

    def handler(event: DummyEvent) -> None:
        received.append(event)

    bus.subscribe(DummyEvent, handler)
    bus.unsubscribe(DummyEvent, handler)
    bus.publish(DummyEvent("hello"))

    assert received == []


def test_unsubscribe_unknown_handler_raises_error() -> None:
    """Unsubscribing an unknown handler raises EventHandlerNotFoundError."""
    bus = EventBus()

    def handler(event: DummyEvent) -> None:
        _ = event

    with pytest.raises(EventHandlerNotFoundError):
        bus.unsubscribe(DummyEvent, handler)


def test_handler_can_unsubscribe_during_publish() -> None:
    """A handler can unsubscribe itself while an event is being published."""
    bus = EventBus()
    received: list[DummyEvent] = []

    def handler(event: DummyEvent) -> None:
        received.append(event)
        bus.unsubscribe(DummyEvent, handler)

    bus.subscribe(DummyEvent, handler)

    first_event = DummyEvent("first")
    second_event = DummyEvent("second")

    bus.publish(first_event)
    bus.publish(second_event)

    assert received == [first_event]
