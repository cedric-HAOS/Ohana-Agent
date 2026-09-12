"""Task registry for scheduled tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ohana_agent.scheduler.task import Task


@dataclass
class TaskRegistry:
    """Store and query scheduled tasks."""

    tasks: dict[str, Task] = field(default_factory=dict)

    def add(self, task: Task) -> None:
        """Add a task."""
        if task.id in self.tasks:
            msg = f"task already exists: {task.id}"
            raise ValueError(msg)

        self.tasks[task.id] = task

    def remove(self, task_id: str) -> Task:
        """Remove a task."""
        try:
            return self.tasks.pop(task_id)
        except KeyError as exc:
            msg = f"task not found: {task_id}"
            raise KeyError(msg) from exc

    def get(self, task_id: str) -> Task:
        """Return a task by id."""
        try:
            return self.tasks[task_id]
        except KeyError as exc:
            msg = f"task not found: {task_id}"
            raise KeyError(msg) from exc

    def exists(self, task_id: str) -> bool:
        """Return True if a task exists."""
        return task_id in self.tasks

    def list(self) -> list[Task]:
        """Return all tasks ordered by priority."""
        return sorted(self.tasks.values(), key=lambda task: (task.priority, task.name))

    def due_tasks(self, now: datetime) -> list[Task]:
        """Return enabled tasks due at the given datetime."""
        return sorted(
            (task for task in self.tasks.values() if task.is_due(now)),
            key=lambda task: (task.priority, task.name),
        )

    def clear(self) -> None:
        """Remove all tasks."""
        self.tasks.clear()
