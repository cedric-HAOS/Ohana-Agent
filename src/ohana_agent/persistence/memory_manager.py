"""Memory manager facade."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .memory_entry import MemoryEntry
from .memory_scope import MemoryScope
from .memory_statistics import MemoryStatistics
from .memory_storage import MemoryStorage
from .persistent_memory import PersistentMemory
from .runtime_memory import RuntimeMemory
from .session_memory import SessionMemory


class MemoryManager:
    """Facade for memory operations."""

    def __init__(
        self,
        runtime_memory: RuntimeMemory | None = None,
        session_memory: SessionMemory | None = None,
        persistent_memory: PersistentMemory | None = None,
        storage: MemoryStorage | None = None,
    ) -> None:
        """Initialize memory manager."""
        self._runtime_memory = runtime_memory or RuntimeMemory()
        self._session_memory = session_memory or SessionMemory()
        self._persistent_memory = persistent_memory or PersistentMemory()
        self._storage = storage

        self._memories = {
            MemoryScope.RUNTIME: self._runtime_memory,
            MemoryScope.SESSION: self._session_memory,
            MemoryScope.PERSISTENT: self._persistent_memory,
        }

        self._statistics = MemoryStatistics()

    @property
    def statistics(self) -> MemoryStatistics:
        """Return memory statistics."""
        return self._statistics

    def set(
        self,
        key: str,
        value: Any,
        scope: MemoryScope = MemoryScope.RUNTIME,
    ) -> None:
        """Store or replace a value in the selected memory scope."""
        self._select_memory(scope).set(key, value)
        self._statistics.sets += 1

    def get(
        self,
        key: str,
        scope: MemoryScope = MemoryScope.RUNTIME,
    ) -> Any | None:
        """Return a value or None if absent."""
        value = self._select_memory(scope).get(key)

        if value is None:
            self._statistics.misses += 1
        else:
            self._statistics.hits += 1

        return value

    def delete(
        self,
        key: str,
        scope: MemoryScope = MemoryScope.RUNTIME,
    ) -> None:
        """Delete a value if present."""
        self._select_memory(scope).delete(key)
        self._statistics.deletes += 1

    def exists(
        self,
        key: str,
        scope: MemoryScope = MemoryScope.RUNTIME,
    ) -> bool:
        """Return True if a key exists."""
        return self._select_memory(scope).exists(key)

    def clear(
        self,
        scope: MemoryScope = MemoryScope.RUNTIME,
    ) -> None:
        """Clear the selected memory scope."""
        self._select_memory(scope).clear()
        self._statistics.clears += 1

    def keys(
        self,
        scope: MemoryScope = MemoryScope.RUNTIME,
    ) -> list[str]:
        """Return keys from the selected memory scope."""
        return self._select_memory(scope).keys()

    def values(
        self,
        scope: MemoryScope = MemoryScope.RUNTIME,
    ) -> list[Any]:
        """Return values from the selected memory scope."""
        return self._select_memory(scope).values()

    def items(
        self,
        scope: MemoryScope = MemoryScope.RUNTIME,
    ) -> list[tuple[str, Any]]:
        """Return items from the selected memory scope."""
        return self._select_memory(scope).items()

    def save_persistent(self) -> None:
        """Save persistent memory using the configured storage."""
        if self._storage is None:
            return

        self._storage.save(list(self._persistent_memory))
        self._statistics.saves += 1

    def load_persistent(self) -> None:
        """Load persistent memory using the configured storage."""
        if self._storage is None:
            return

        self._persistent_memory.clear()

        for entry in self._storage.load():
            self._persistent_memory.set(
                key=entry.key,
                value=entry.value,
            )

        self._statistics.loads += 1

    def _select_memory(
        self,
        scope: MemoryScope,
    ) -> RuntimeMemory | SessionMemory | PersistentMemory:
        """Select memory implementation from scope."""
        try:
            return self._memories[scope]
        except KeyError as exc:
            msg = f"Unsupported memory scope: {scope}"
            raise ValueError(msg) from exc

    def __contains__(self, key: object) -> bool:
        """Support 'in' operator on runtime memory."""
        return key in self._runtime_memory

    def __len__(self) -> int:
        """Return number of runtime entries."""
        return len(self._runtime_memory)

    def __iter__(self) -> Iterator[MemoryEntry]:
        """Iterate over runtime entries."""
        return iter(self._runtime_memory)
