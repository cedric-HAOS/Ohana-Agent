"""Tests for the Shikamaru Command base class."""

from dataclasses import dataclass
from datetime import UTC
from uuid import UUID

from ohana_agent.core.command import Command


@dataclass(slots=True)
class DummyCommand(Command):
    """Dummy command used for testing."""

    value: str = ""


def test_command_has_unique_id() -> None:
    """Each command has a unique identifier."""
    command1 = Command()
    command2 = Command()

    assert command1.id != command2.id


def test_command_id_is_valid_uuid() -> None:
    """The command identifier is a valid UUID."""
    command = Command()

    uuid = UUID(command.id)

    assert str(uuid) == command.id


def test_command_timestamp_is_utc() -> None:
    """The command timestamp is timezone-aware and in UTC."""
    command = Command()

    assert command.timestamp.tzinfo == UTC


def test_command_can_be_extended() -> None:
    """Custom commands inherit common metadata."""
    command = DummyCommand(value="Hello")

    assert command.value == "Hello"
    assert isinstance(command.id, str)
    assert command.timestamp.tzinfo == UTC
