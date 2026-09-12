"""Runtime memory implementation."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .memory_entry import MemoryEntry
from .memory_scope import MemoryScope


class RuntimeMemory:
    """In-memory volatile storage."""

    def __init__(self) -> None:
        """Initialize an empty runtime memory."""
        self._entries: dict[str, MemoryEntry] = {}

    def set(self, key: str, value: Any) -> None:
        """Store or replace a value."""
        self._entries[key] = MemoryEntry(
            key=key,
            value=value,
            scope=MemoryScope.RUNTIME,
        )

    def get(self, key: str) -> Any | None:
        """Return a value or None if absent."""
        entry = self._entries.get(key)
        return None if entry is None else entry.value

    def delete(self, key: str) -> None:
        """Delete a value if present."""
        self._entries.pop(key, None)

    def exists(self, key: str) -> bool:
        """Return True if a key exists."""
        return key in self._entries

    def clear(self) -> None:
        """Remove all entries."""
        self._entries.clear()

    def keys(self) -> list[str]:
        """Return all keys."""
        return list(self._entries.keys())

    def values(self) -> list[Any]:
        """Return all stored values."""
        return [entry.value for entry in self._entries.values()]

    def items(self) -> list[tuple[str, Any]]:
        """Return (key, value) pairs."""
        return [(entry.key, entry.value) for entry in self._entries.values()]

    def __contains__(self, key: object) -> bool:
        """Support 'in' operator."""
        if not isinstance(key, str):
            return False
        return key in self._entries

    def __len__(self) -> int:
        """Return number of stored entries."""
        return len(self._entries)

    def __iter__(self) -> Iterator[MemoryEntry]:
        """Iterate over MemoryEntry objects."""
        return iter(self._entries.values())
