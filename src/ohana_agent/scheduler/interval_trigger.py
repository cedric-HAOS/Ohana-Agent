"""Interval trigger implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ohana_agent.scheduler.base_trigger import BaseTrigger


@dataclass
class IntervalTrigger(BaseTrigger):
    """Trigger executed repeatedly after a fixed interval."""

    interval: timedelta
    start_at: datetime | None = None
    last_run_at: datetime | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        super().__init__()

        if self.interval.total_seconds() <= 0:
            msg = "interval must be greater than zero"
            raise ValueError(msg)

    def next_run_at(self, after: datetime) -> datetime:
        if self.last_run_at is not None:
            return self.last_run_at + self.interval

        if self.start_at is not None:
            if after <= self.start_at:
                return self.start_at

            elapsed = after - self.start_at
            steps = int(elapsed.total_seconds() // self.interval.total_seconds()) + 1
            return self.start_at + (self.interval * steps)

        return after + self.interval

    def is_due(self, now: datetime) -> bool:
        if self.last_run_at is None and self.start_at is not None:
            return now >= self.start_at

        if self.last_run_at is None:
            return False

        return now >= self.last_run_at + self.interval

    def _mark_executed(self, executed_at: datetime) -> None:
        self.last_run_at = executed_at
