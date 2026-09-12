"""Memory statistics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MemoryStatistics:
    """Memory manager statistics."""

    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    clears: int = 0
    saves: int = 0
    loads: int = 0

    def reset(self) -> None:
        """Reset all statistics."""
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.deletes = 0
        self.clears = 0
        self.saves = 0
        self.loads = 0
