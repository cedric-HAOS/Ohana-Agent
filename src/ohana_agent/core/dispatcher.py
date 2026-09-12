"""Command dispatcher for Shikamaru."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from ohana_agent.core.command import Command
from ohana_agent.core.event import Event
from ohana_agent.core.events import EventBus

C = TypeVar("C", bound=Command)
CommandHandler = Callable[[C], Any]


class CommandDispatcherError(Exception):
    """Base exception for command dispatcher errors."""


class CommandAlreadyRegisteredError(CommandDispatcherError):
    """Raised when a command is already registered."""


class CommandNotFoundError(CommandDispatcherError):
    """Raised when a command is not registered."""


@dataclass(slots=True)
class CommandDispatched(Event):
    """Event published when a command is dispatched."""

    command_id: str = ""
    command_type: str = ""


@dataclass(slots=True)
class CommandSucceeded(Event):
    """Event published when a command succeeds."""

    command_id: str = ""
    command_type: str = ""


@dataclass(slots=True)
class CommandFailed(Event):
    """Event published when a command fails."""

    command_id: str = ""
    command_type: str = ""
    error: str = ""


class CommandDispatcher:
    """Route commands to registered handlers."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus if event_bus is not None else EventBus()
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, command_type: type[C], handler: CommandHandler[C]) -> None:
        """Register a command handler."""
        if command_type in self._handlers:
            raise CommandAlreadyRegisteredError(
                f"Command already registered: {command_type.__name__}"
            )

        self._handlers[command_type] = handler

    def dispatch(self, command: object) -> object:
        """Dispatch a command to its registered handler."""
        command_type = type(command)

        if command_type not in self._handlers:
            raise CommandNotFoundError(
                f"Command handler not found: {command_type.__name__}"
            )

        handler = self._handlers[command_type]
        command_id = getattr(command, "id", "")

        self.event_bus.publish(
            CommandDispatched(
                command_id=command_id,
                command_type=command_type.__name__,
            )
        )

        try:
            result = handler(command)
        except Exception as error:
            self.event_bus.publish(
                CommandFailed(
                    command_id=command_id,
                    command_type=command_type.__name__,
                    error=str(error),
                )
            )
            raise

        self.event_bus.publish(
            CommandSucceeded(
                command_id=command_id,
                command_type=command_type.__name__,
            )
        )

        return result

    def has(self, command_type: type[Command]) -> bool:
        """Return whether a command type is registered."""
        return command_type in self._handlers

    def unregister(self, command_type: type[Command]) -> None:
        """Unregister a command handler."""
        if command_type not in self._handlers:
            raise CommandNotFoundError(f"Command not found: {command_type.__name__}")

        del self._handlers[command_type]

    def commands(self) -> list[type[Command]]:
        """Return registered command types."""
        return list(self._handlers.keys())
