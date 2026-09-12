from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Abstraction over time."""

    def now(self) -> datetime:
        """Return the current datetime."""


class SystemClock:
    """Clock using the system time."""

    def now(self) -> datetime:
        return datetime.now().astimezone()


@dataclass
class FakeClock:
    """Deterministic clock for tests."""

    current_time: datetime

    def now(self) -> datetime:
        return self.current_time

    def advance(self, delta: timedelta) -> None:
        self.current_time += delta
