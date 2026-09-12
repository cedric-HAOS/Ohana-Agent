"""Event subscription definition."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class EventSubscription:
    """Subscription between an event type and a handler."""

    event_type: type[object]
    handler: Callable[[object], None]
