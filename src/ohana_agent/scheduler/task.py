"""Scheduler task model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from ohana_agent.scheduler.base_trigger import BaseTrigger


class TaskState(StrEnum):
    """Possible states for a scheduled task."""

    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    DISABLED = "disabled"


@dataclass
class Task:
    """A schedulable command description."""

    command: str
    trigger: BaseTrigger
    name: str | None = None
    arguments: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    priority: int = 100
    enabled: bool = True
    id: str = field(default_factory=lambda: str(uuid4()))
    state: TaskState = field(default=TaskState.IDLE, init=False)
    last_started_at: datetime | None = field(default=None, init=False)
    last_finished_at: datetime | None = field(default=None, init=False)
    last_failed_at: datetime | None = field(default=None, init=False)
    last_error: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not self.command.strip():
            msg = "task command must not be empty"
            raise ValueError(msg)

        if self.priority < 0:
            msg = "task priority must be greater than or equal to zero"
            raise ValueError(msg)

        if self.name is None:
            self.name = self.command

        if not self.enabled:
            self.state = TaskState.DISABLED

    @property
    def execution_count(self) -> int:
        """Return the number of executions recorded by the trigger."""
        return self.trigger.fire_count

    @property
    def last_execution(self) -> datetime | None:
        """Return the last execution datetime recorded by the trigger."""
        return self.trigger.last_executed_at

    def is_due(self, now: datetime) -> bool:
        """Return True when the task is enabled and its trigger is due."""
        return self.enabled and self.trigger.is_due(now)

    def next_run_at(self, after: datetime) -> datetime | None:
        """Return the next scheduled execution datetime."""
        if not self.enabled:
            return None

        return self.trigger.next_run_at(after)

    def mark_started(self, started_at: datetime) -> None:
        """Mark the task as running."""
        self.state = TaskState.RUNNING
        self.last_started_at = started_at
        self.last_error = None

    def mark_finished(self, finished_at: datetime) -> None:
        """Mark the task as successfully finished."""
        self.state = TaskState.WAITING
        self.last_finished_at = finished_at
        self.trigger.mark_executed(finished_at)

    def mark_failed(self, failed_at: datetime, error: Exception | str) -> None:
        """Mark the task as failed."""
        self.state = TaskState.WAITING
        self.last_failed_at = failed_at
        self.last_error = str(error)
        self.trigger.mark_executed(failed_at)

    def disable(self) -> None:
        """Disable the task."""
        self.enabled = False
        self.state = TaskState.DISABLED

    def enable(self) -> None:
        """Enable the task."""
        self.enabled = True
        self.state = TaskState.IDLE
