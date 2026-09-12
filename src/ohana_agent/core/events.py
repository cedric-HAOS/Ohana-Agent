"""Event bus for internal Shikamaru communication."""

from collections import defaultdict
from collections.abc import Callable
from typing import TypeVar

from ohana_agent.core.event_subscription import EventSubscription

T = TypeVar("T")


class EventBusError(Exception):
    """Base exception for event bus errors."""


class EventHandlerNotFoundError(EventBusError):
    """Raised when trying to unsubscribe an unknown handler."""


class EventBus:
    """Synchronous event bus used to publish events to subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[type[object], list[EventSubscription]] = defaultdict(
            list
        )

    def subscribe(self, event_type: type[T], handler: Callable[[T], None]) -> None:
        """Subscribe a handler to an event type."""
        subscription = EventSubscription(
            event_type=event_type,
            handler=handler,  # type: ignore[arg-type]
        )

        self._subscribers[event_type].append(subscription)

    def unsubscribe(self, event_type: type[T], handler: Callable[[T], None]) -> None:
        """Unsubscribe a handler from an event type."""
        subscriptions = self._subscribers[event_type]

        matching_subscription = next(
            (
                subscription
                for subscription in subscriptions
                if subscription.handler is handler
            ),
            None,
        )

        if matching_subscription is None:
            raise EventHandlerNotFoundError(
                f"Handler not found for event: {event_type.__name__}"
            )

        subscriptions.remove(matching_subscription)

    def publish(self, event: object) -> None:
        """Publish an event to all matching subscribers."""
        event_type = type(event)

        for subscription in list(self._subscribers[event_type]):
            subscription.handler(event)
