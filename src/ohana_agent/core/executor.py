"""Core executor abstraction."""

from __future__ import annotations

from typing import Protocol, TypeVar

T = TypeVar("T")
R = TypeVar("R")


class Executor(Protocol[T, R]):
    """Base executor contract."""

    def execute(self, item: T) -> R:
        """Execute an item."""
