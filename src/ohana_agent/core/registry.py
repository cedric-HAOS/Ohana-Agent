"""Core registry abstraction."""

from __future__ import annotations

from typing import Protocol, TypeVar

T = TypeVar("T")


class Registry(Protocol[T]):
    """Base registry contract."""

    def add(self, item: T) -> None:
        """Add an item."""

    def remove(self, item_id: str) -> T:
        """Remove an item."""

    def get(self, item_id: str) -> T:
        """Return an item by id."""

    def exists(self, item_id: str) -> bool:
        """Return True if an item exists."""

    def clear(self) -> None:
        """Remove all items."""
