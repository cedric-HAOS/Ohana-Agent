"""Tests for the Shikamaru Event base class."""

from dataclasses import dataclass
from datetime import UTC
from uuid import UUID

from ohana_agent.core.event import Event


@dataclass(slots=True)
class DummyEvent(Event):
    """Dummy event used for testing."""

    message: str = ""


def test_event_has_unique_id() -> None:
    """Each event has a unique identifier."""
    event1 = Event()
    event2 = Event()

    assert event1.id != event2.id


def test_event_id_is_valid_uuid() -> None:
    """The event identifier is a valid UUID."""
    event = Event()

    uuid = UUID(event.id)

    assert str(uuid) == event.id


def test_event_timestamp_is_utc() -> None:
    """The event timestamp is timezone-aware and in UTC."""
    event = Event()

    assert event.timestamp.tzinfo == UTC


def test_event_can_be_extended() -> None:
    """Custom events inherit common metadata."""
    event = DummyEvent(message="Hello")

    assert event.message == "Hello"
    assert isinstance(event.id, str)
    assert event.timestamp.tzinfo == UTC
