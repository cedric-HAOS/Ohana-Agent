"""Persistent memory implementation."""

from __future__ import annotations

from typing import Any

from .memory_entry import MemoryEntry
from .memory_scope import MemoryScope
from .runtime_memory import RuntimeMemory


class PersistentMemory(RuntimeMemory):
    """In-memory persistent-scope storage.

    Persistence backend will be introduced later.
    """

    def set(self, key: str, value: Any) -> None:
        """Store or replace a persistent value."""
        self._entries[key] = MemoryEntry(
            key=key,
            value=value,
            scope=MemoryScope.PERSISTENT,
        )
