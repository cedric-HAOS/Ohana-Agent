"""Event publisher contract."""

from typing import Protocol


class EventPublisher(Protocol):
    """Minimal contract required to publish domain events."""

    def publish(self, event: object) -> None:
        """Publish a domain event."""
