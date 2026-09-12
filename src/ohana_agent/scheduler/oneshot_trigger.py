"""One-shot trigger implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ohana_agent.scheduler.base_trigger import BaseTrigger


@dataclass
class OneShotTrigger(BaseTrigger):
    """Trigger executed once at a specific datetime."""

    run_at: datetime
    executed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        super().__init__()

    def next_run_at(self, after: datetime) -> datetime | None:
        if self.executed:
            return None

        if after <= self.run_at:
            return self.run_at

        return None

    def is_due(self, now: datetime) -> bool:
        return not self.executed and now >= self.run_at

    def _mark_executed(self, executed_at: datetime) -> None:
        self.executed = True
