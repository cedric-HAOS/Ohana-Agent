"""Task executor abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ohana_agent.scheduler.task import Task


@dataclass(frozen=True)
class TaskExecutionResult:
    """Result of a task execution."""

    task_id: str
    command: str
    success: bool
    started_at: datetime
    finished_at: datetime
    error: str | None = None


class TaskExecutor(Protocol):
    """Protocol for task executors."""

    def execute(self, task: Task, now: datetime) -> TaskExecutionResult:
        """Execute a scheduled task."""


class DryRunTaskExecutor:
    """Task executor used for tests and simulations."""

    def execute(self, task: Task, now: datetime) -> TaskExecutionResult:
        """Pretend to execute a task successfully."""
        task.mark_started(now)
        task.mark_finished(now)

        return TaskExecutionResult(
            task_id=task.id,
            command=task.command,
            success=True,
            started_at=now,
            finished_at=now,
        )


class FailingTaskExecutor:
    """Task executor used to simulate failures."""

    def __init__(self, error: Exception | str = "task execution failed") -> None:
        self.error = error

    def execute(self, task: Task, now: datetime) -> TaskExecutionResult:
        """Pretend to execute a task and fail."""
        task.mark_started(now)
        task.mark_failed(now, self.error)

        return TaskExecutionResult(
            task_id=task.id,
            command=task.command,
            success=False,
            started_at=now,
            finished_at=now,
            error=str(self.error),
        )
