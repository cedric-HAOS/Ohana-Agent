"""Scheduler orchestration service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol

from ohana_agent.scheduler.clock import Clock, SystemClock
from ohana_agent.scheduler.scheduler_events import (
    ScheduledTaskExecuted,
    ScheduledTaskFailed,
    ScheduledTaskTriggered,
    SchedulerStarted,
    SchedulerStopped,
    SchedulerTicked,
)
from ohana_agent.scheduler.scheduler_runtime import SchedulerRuntime
from ohana_agent.scheduler.task import Task
from ohana_agent.scheduler.task_executor import (
    DryRunTaskExecutor,
    TaskExecutionResult,
    TaskExecutor,
)
from ohana_agent.scheduler.task_registry import TaskRegistry


class SchedulerEventBus(Protocol):
    """Minimal event bus contract required by the scheduler."""

    def publish(self, event: object) -> None:
        """Publish an event."""


@dataclass
class Scheduler:
    """Orchestrate scheduled tasks."""

    clock: Clock = field(default_factory=SystemClock)
    registry: TaskRegistry = field(default_factory=TaskRegistry)
    executor: TaskExecutor = field(default_factory=DryRunTaskExecutor)
    runtime: SchedulerRuntime = field(default_factory=SchedulerRuntime)
    event_bus: SchedulerEventBus | None = None

    @property
    def running(self) -> bool:
        """Return True when the scheduler is running."""
        return self.runtime.running

    def start(self) -> None:
        """Start the scheduler."""
        now = self.clock.now()
        self.runtime.mark_starting()
        self.runtime.mark_running(now)
        self._publish_event(SchedulerStarted())

    def stop(self) -> None:
        """Stop the scheduler."""
        now = self.clock.now()
        self.runtime.mark_stopping()
        self.runtime.mark_stopped(now)
        self._publish_event(SchedulerStopped())

    def add_task(self, task: Task) -> None:
        """Add a task to the scheduler."""
        self.registry.add(task)

    def remove_task(self, task_id: str) -> Task:
        """Remove a task from the scheduler."""
        return self.registry.remove(task_id)

    def get_task(self, task_id: str) -> Task:
        """Return a task by id."""
        return self.registry.get(task_id)

    def list_tasks(self) -> list[Task]:
        """Return all registered tasks ordered by priority."""
        return self.registry.list()

    def request_runs(
        self, matches: Callable[[Task], bool], delays: tuple[timedelta, ...]
    ) -> list[str]:
        """Request extra runs of every enabled task selected by ``matches``."""
        now = self.clock.now()
        matched = [
            task for task in self.registry.list() if task.enabled and matches(task)
        ]
        for task in matched:
            for delay in delays:
                task.request_run(now + delay)
        return [task.id for task in matched]

    def due_tasks(self) -> list[Task]:
        """Return enabled tasks due at the scheduler current datetime."""
        return self.registry.due_tasks(self.clock.now())

    def tick(self) -> list[TaskExecutionResult]:
        """Execute due tasks for one scheduler tick."""
        if not self.running:
            return []

        now = self.clock.now()
        self.runtime.record_tick(now)
        self._publish_event(SchedulerTicked())

        results: list[TaskExecutionResult] = []

        for task in self.registry.due_tasks(now):
            self._publish_event(
                ScheduledTaskTriggered(
                    task_name=task.name,
                    command=task.command,
                    arguments=task.arguments,
                )
            )

            result = self.executor.execute(task, now)
            results.append(result)

            self.runtime.statistics.record_task_result(result.success)

            if result.success:
                self._publish_event(
                    ScheduledTaskExecuted(
                        task_name=task.name,
                        command=task.command,
                        arguments=task.arguments,
                        result=result,
                    )
                )
            else:
                self._publish_event(
                    ScheduledTaskFailed(
                        task_name=task.name,
                        command=task.command,
                        arguments=task.arguments,
                        error=result.error or "",
                    )
                )

        return results

    def _publish_event(self, event: object) -> None:
        """Publish a scheduler event if an event bus is available."""
        if self.event_bus is not None:
            self.event_bus.publish(event)
