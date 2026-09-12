"""Base class for all scheduler triggers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class BaseTrigger(ABC):
    """Abstract base class for all scheduler triggers."""

    def __init__(self) -> None:
        self._fire_count = 0
        self._last_executed_at: datetime | None = None

    @property
    def fire_count(self) -> int:
        """Return the number of times the trigger has fired."""
        return self._fire_count

    @property
    def last_executed_at(self) -> datetime | None:
        """Return the datetime of the last execution."""
        return self._last_executed_at

    @abstractmethod
    def next_run_at(self, after: datetime) -> datetime | None:
        """Return the next scheduled execution."""

    @abstractmethod
    def is_due(self, now: datetime) -> bool:
        """Return True when the trigger should fire."""

    def mark_executed(self, executed_at: datetime) -> None:
        """Record an execution and delegate trigger-specific updates."""
        self._fire_count += 1
        self._last_executed_at = executed_at
        self._mark_executed(executed_at)

    @abstractmethod
    def _mark_executed(self, executed_at: datetime) -> None:
        """Update the trigger internal state after execution."""
