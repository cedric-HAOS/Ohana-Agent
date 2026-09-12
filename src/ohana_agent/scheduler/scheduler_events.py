"""Scheduler domain events."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class SchedulerEvent:
    """Base class for scheduler events."""

    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class SchedulerStarted(SchedulerEvent):
    """Event emitted when the scheduler starts."""


@dataclass(frozen=True)
class SchedulerStopped(SchedulerEvent):
    """Event emitted when the scheduler stops."""


@dataclass(frozen=True)
class SchedulerTicked(SchedulerEvent):
    """Event emitted when the scheduler ticks."""


@dataclass(frozen=True)
class ScheduledTaskTriggered(SchedulerEvent):
    """Event emitted when a scheduled task is triggered."""

    task_name: str = ""
    command: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScheduledTaskExecuted(SchedulerEvent):
    """Event emitted when a scheduled task is successfully executed."""

    task_name: str = ""
    command: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Any = None


@dataclass(frozen=True)
class ScheduledTaskFailed(SchedulerEvent):
    """Event emitted when a scheduled task execution fails."""

    task_name: str = ""
    command: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    error: str = ""
