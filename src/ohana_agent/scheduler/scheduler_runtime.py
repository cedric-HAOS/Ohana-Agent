"""Scheduler runtime state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ohana_agent.scheduler.scheduler_state import SchedulerState
from ohana_agent.scheduler.scheduler_statistics import SchedulerStatistics


@dataclass
class SchedulerRuntime:
    """Runtime information for the scheduler."""

    state: SchedulerState = SchedulerState.STOPPED
    statistics: SchedulerStatistics = field(default_factory=SchedulerStatistics)
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    last_tick_at: datetime | None = None

    @property
    def running(self) -> bool:
        """Return True when the scheduler is running."""
        return self.state == SchedulerState.RUNNING

    def mark_starting(self) -> None:
        """Mark the scheduler as starting."""
        self.state = SchedulerState.STARTING

    def mark_running(self, started_at: datetime) -> None:
        """Mark the scheduler as running."""
        self.state = SchedulerState.RUNNING
        self.started_at = started_at
        self.stopped_at = None

    def mark_stopping(self) -> None:
        """Mark the scheduler as stopping."""
        self.state = SchedulerState.STOPPING

    def mark_stopped(self, stopped_at: datetime) -> None:
        """Mark the scheduler as stopped."""
        self.state = SchedulerState.STOPPED
        self.stopped_at = stopped_at

    def record_tick(self, tick_at: datetime) -> None:
        """Record a scheduler tick."""
        self.last_tick_at = tick_at
        self.statistics.record_tick()
