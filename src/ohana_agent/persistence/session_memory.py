"""Session memory implementation."""

from __future__ import annotations

from typing import Any

from .memory_scope import MemoryScope
from .runtime_memory import RuntimeMemory


class SessionMemory(RuntimeMemory):
    """In-memory session storage."""

    def set(self, key: str, value: Any) -> None:
        """Store or replace a session value."""
        from .memory_entry import MemoryEntry

        self._entries[key] = MemoryEntry(
            key=key,
            value=value,
            scope=MemoryScope.SESSION,
        )
