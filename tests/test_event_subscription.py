"""Tests for event subscriptions."""

from ohana_agent.core.event_subscription import EventSubscription


class DummyEvent:
    pass


def test_event_subscription_stores_event_type() -> None:
    def handler(event: DummyEvent) -> None:
        _ = event

    subscription = EventSubscription(
        event_type=DummyEvent,
        handler=handler,
    )

    assert subscription.event_type is DummyEvent


def test_event_subscription_stores_handler() -> None:
    def handler(event: DummyEvent) -> None:
        _ = event

    subscription = EventSubscription(
        event_type=DummyEvent,
        handler=handler,
    )

    assert subscription.handler is handler


def test_event_subscription_equality() -> None:
    def handler(event: DummyEvent) -> None:
        _ = event

    first = EventSubscription(
        event_type=DummyEvent,
        handler=handler,
    )
    second = EventSubscription(
        event_type=DummyEvent,
        handler=handler,
    )

    assert first == second


def test_event_subscription_is_immutable() -> None:
    def handler(event: DummyEvent) -> None:
        _ = event

    subscription = EventSubscription(
        event_type=DummyEvent,
        handler=handler,
    )

    try:
        subscription.event_type = object  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("EventSubscription should be immutable")
