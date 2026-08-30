"""Task executor backed by the dispatcher."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from threading import Thread
from typing import Protocol

from monitoring import MonitoringScheduleRegistry
from scheduler.task import Task
from scheduler.task_executor import TaskExecutionResult

LOGGER = logging.getLogger(__name__)


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
    job_runner: Callable[[dict[str, object], datetime], object] | None = None
    wake_dispatcher: Callable[[datetime], object] | None = None
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
            if task.command == "jobs.logs.health_check":
                if self.job_runner is None:
                    raise RuntimeError("distributed log job runner is unavailable")
                self.job_runner(task.arguments, now)
            elif task.command == "jobs.wake.dispatch":
                if self.wake_dispatcher is None:
                    raise RuntimeError("distributed wake dispatcher is unavailable")
                self.wake_dispatcher(now)
            elif task.command == "backup.run":
                self._dispatch_backup_in_background(task.arguments)
            else:
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

    def _dispatch_backup_in_background(
        self,
        arguments: dict[str, object],
    ) -> None:
        """Run one scheduled backup without blocking scheduler maintenance tasks."""
        copied_arguments = dict(arguments)
        target_id = str(copied_arguments.get("target_id", "unknown"))

        def run() -> None:
            try:
                self.dispatcher.execute("backup.run", copied_arguments)
            except Exception:  # noqa: BLE001
                LOGGER.exception(
                    "Scheduled backup dispatch failed for %s",
                    target_id,
                )

        Thread(
            target=run,
            name=f"ohana-scheduled-backup-{target_id}",
            daemon=True,
        ).start()
