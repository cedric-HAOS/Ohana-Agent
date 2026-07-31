"""Task executor backed by the dispatcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from monitoring import MonitoringScheduleRegistry
from scheduler.task import Task
from scheduler.task_executor import TaskExecutionResult


class DispatcherLike(Protocol):
    """Minimal dispatcher contract required by the scheduler."""

    def execute(
        self,
        command: str,
        arguments: dict[str, object] | None = None,
    ) -> object:
        """Execute a command."""

    def publish_suspended(
        self,
        command: str,
        arguments: dict[str, object],
        *,
        reason: str,
        next_activation: datetime | None,
    ) -> object:
        """Publish a suspended observation without executing the plugin."""


@dataclass
class DispatcherTaskExecutor:
    """Execute scheduled tasks through the dispatcher."""

    dispatcher: DispatcherLike
    monitoring_registry: MonitoringScheduleRegistry | None = None
    _suspended_tasks: set[str] = field(default_factory=set, init=False, repr=False)

    def execute(self, task: Task, now: datetime) -> TaskExecutionResult:
        """Execute a task using the dispatcher."""
        task.mark_started(now)

        if self.monitoring_registry is not None:
            node_id = task.metadata.get("node_id")
            decision = self.monitoring_registry.decision(
                node_id if isinstance(node_id, str) else None,
                now,
            )
            if not decision.active:
                if task.id not in self._suspended_tasks:
                    self.dispatcher.publish_suspended(
                        task.command,
                        task.arguments,
                        reason=decision.reason or "Surveillance suspendue.",
                        next_activation=decision.next_activation,
                    )
                    self._suspended_tasks.add(task.id)
                task.mark_finished(now)
                return TaskExecutionResult(
                    task_id=task.id,
                    command=task.command,
                    success=True,
                    started_at=now,
                    finished_at=now,
                )
            self._suspended_tasks.discard(task.id)

        try:
            self.dispatcher.execute(task.command, task.arguments)
        except Exception as exc:
            task.mark_failed(now, exc)

            return TaskExecutionResult(
                task_id=task.id,
                command=task.command,
                success=False,
                started_at=now,
                finished_at=now,
                error=str(exc),
            )

        task.mark_finished(now)

        return TaskExecutionResult(
            task_id=task.id,
            command=task.command,
            success=True,
            started_at=now,
            finished_at=now,
        )
