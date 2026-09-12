from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Trigger(Protocol):
    """Base protocol for all scheduler triggers."""

    def next_run_at(self, after: datetime) -> datetime | None:
        """Return the next execution datetime after the given datetime."""

    def is_due(self, now: datetime) -> bool:
        """Return whether the trigger is due at the given datetime."""

    def mark_executed(self, executed_at: datetime) -> None:
        """Update internal state after execution."""
