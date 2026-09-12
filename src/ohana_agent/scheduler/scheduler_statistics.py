"""Scheduler runtime statistics."""

from dataclasses import dataclass


@dataclass
class SchedulerStatistics:
    """Runtime statistics for the scheduler."""

    tasks_executed: int = 0
    tasks_failed: int = 0
    tick_count: int = 0

    def record_tick(self) -> None:
        """Record a scheduler tick."""
        self.tick_count += 1

    def record_task_result(self, success: bool) -> None:
        """Record a task execution result."""
        if success:
            self.tasks_executed += 1
        else:
            self.tasks_failed += 1
