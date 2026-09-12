"""Tests for the Shikamaru command dispatcher."""

from dataclasses import dataclass

import pytest

from ohana_agent.core.command import Command
from ohana_agent.core.dispatcher import (
    CommandAlreadyRegisteredError,
    CommandDispatched,
    CommandDispatcher,
    CommandFailed,
    CommandNotFoundError,
    CommandSucceeded,
)
from ohana_agent.core.events import EventBus


@dataclass(slots=True)
class DummyCommand(Command):
    """Dummy command used for dispatcher tests."""

    value: str = ""


@dataclass(slots=True)
class AnotherCommand(Command):
    """Another command used for dispatcher tests."""

    value: str = ""


def test_register_command() -> None:
    """A command handler can be registered."""
    bus = EventBus()
    dispatcher = CommandDispatcher(bus)

    def handler(command: DummyCommand) -> None:
        _ = command

    dispatcher.register(DummyCommand, handler)

    assert dispatcher.has(DummyCommand) is True


def test_register_duplicate_command_raises_error() -> None:
    """Registering the same command type twice raises an error."""
    bus = EventBus()
    dispatcher = CommandDispatcher(bus)

    def handler(command: DummyCommand) -> None:
        _ = command

    dispatcher.register(DummyCommand, handler)

    with pytest.raises(CommandAlreadyRegisteredError):
        dispatcher.register(DummyCommand, handler)


def test_dispatch_command() -> None:
    """A registered command can be dispatched."""
    bus = EventBus()
    dispatcher = CommandDispatcher(bus)
    calls: list[str] = []

    def handler(command: DummyCommand) -> None:
        calls.append(command.value)

    dispatcher.register(DummyCommand, handler)
    dispatcher.dispatch(DummyCommand(value="called"))

    assert calls == ["called"]


def test_dispatch_command_returns_handler_result() -> None:
    """dispatch() returns the handler result."""
    bus = EventBus()
    dispatcher = CommandDispatcher(bus)

    def handler(command: DummyCommand) -> str:
        return command.value

    dispatcher.register(DummyCommand, handler)

    assert dispatcher.dispatch(DummyCommand(value="ok")) == "ok"


def test_dispatch_unknown_command_raises_error() -> None:
    """Dispatching an unknown command raises an error."""
    bus = EventBus()
    dispatcher = CommandDispatcher(bus)

    with pytest.raises(CommandNotFoundError):
        dispatcher.dispatch(DummyCommand(value="unknown"))


def test_unregister_command() -> None:
    """A command handler can be unregistered."""
    bus = EventBus()
    dispatcher = CommandDispatcher(bus)

    def handler(command: DummyCommand) -> None:
        _ = command

    dispatcher.register(DummyCommand, handler)
    dispatcher.unregister(DummyCommand)

    assert dispatcher.has(DummyCommand) is False


def test_unregister_unknown_command_raises_error() -> None:
    """Unregistering an unknown command raises an error."""
    bus = EventBus()
    dispatcher = CommandDispatcher(bus)

    with pytest.raises(CommandNotFoundError):
        dispatcher.unregister(DummyCommand)


def test_commands_returns_copy() -> None:
    """commands() returns a copy of registered command types."""
    bus = EventBus()
    dispatcher = CommandDispatcher(bus)

    def handler(command: DummyCommand) -> None:
        _ = command

    dispatcher.register(DummyCommand, handler)

    commands = dispatcher.commands()
    commands.clear()

    assert dispatcher.commands() == [DummyCommand]


def test_handlers_are_registered_by_command_type() -> None:
    """Different command types can have different handlers."""
    bus = EventBus()
    dispatcher = CommandDispatcher(bus)
    calls: list[str] = []

    def dummy_handler(command: DummyCommand) -> None:
        calls.append(f"dummy:{command.value}")

    def another_handler(command: AnotherCommand) -> None:
        calls.append(f"another:{command.value}")

    dispatcher.register(DummyCommand, dummy_handler)
    dispatcher.register(AnotherCommand, another_handler)

    dispatcher.dispatch(DummyCommand(value="one"))
    dispatcher.dispatch(AnotherCommand(value="two"))

    assert calls == ["dummy:one", "another:two"]


def test_dispatch_publishes_command_dispatched_event() -> None:
    """Dispatching a command publishes CommandDispatched."""
    bus = EventBus()
    dispatcher = CommandDispatcher(bus)
    received: list[CommandDispatched] = []

    def event_handler(event: CommandDispatched) -> None:
        received.append(event)

    def command_handler(command: DummyCommand) -> None:
        _ = command

    bus.subscribe(CommandDispatched, event_handler)

    command = DummyCommand(value="hello")

    dispatcher.register(DummyCommand, command_handler)
    dispatcher.dispatch(command)

    assert len(received) == 1
    assert received[0].command_id == command.id
    assert received[0].command_type == "DummyCommand"


def test_dispatch_publishes_command_succeeded_event() -> None:
    """A successful command publishes CommandSucceeded."""
    bus = EventBus()
    dispatcher = CommandDispatcher(bus)
    received: list[CommandSucceeded] = []

    def event_handler(event: CommandSucceeded) -> None:
        received.append(event)

    def command_handler(command: DummyCommand) -> None:
        _ = command

    bus.subscribe(CommandSucceeded, event_handler)

    command = DummyCommand(value="hello")

    dispatcher.register(DummyCommand, command_handler)
    dispatcher.dispatch(command)

    assert len(received) == 1
    assert received[0].command_id == command.id
    assert received[0].command_type == "DummyCommand"


def test_dispatch_publishes_command_failed_event() -> None:
    """A failing command publishes CommandFailed."""
    bus = EventBus()
    dispatcher = CommandDispatcher(bus)
    received: list[CommandFailed] = []

    def event_handler(event: CommandFailed) -> None:
        received.append(event)

    def command_handler(command: DummyCommand) -> None:
        _ = command
        raise RuntimeError("boom")

    bus.subscribe(CommandFailed, event_handler)

    command = DummyCommand(value="hello")

    dispatcher.register(DummyCommand, command_handler)

    with pytest.raises(RuntimeError, match="boom"):
        dispatcher.dispatch(command)

    assert len(received) == 1
    assert received[0].command_id == command.id
    assert received[0].command_type == "DummyCommand"
    assert received[0].error == "boom"
