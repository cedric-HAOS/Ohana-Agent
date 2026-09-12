"""Memory entry serialization."""

from __future__ import annotations

from typing import Any

from .memory_entry import MemoryEntry
from .memory_scope import MemoryScope


class MemorySerializer:
    """Serialize and deserialize memory entries."""

    def serialize_entry(self, entry: MemoryEntry) -> dict[str, Any]:
        """Serialize one memory entry."""
        return {
            "key": entry.key,
            "value": entry.value,
            "scope": entry.scope.name,
        }

    def deserialize_entry(self, payload: dict[str, Any]) -> MemoryEntry:
        """Deserialize one memory entry."""
        return MemoryEntry(
            key=payload["key"],
            value=payload["value"],
            scope=MemoryScope[payload["scope"]],
        )

    def serialize_entries(
        self,
        entries: list[MemoryEntry],
    ) -> dict[str, dict[str, Any]]:
        """Serialize memory entries indexed by key."""
        return {entry.key: self.serialize_entry(entry) for entry in entries}

    def deserialize_entries(
        self,
        payload: dict[str, dict[str, Any]],
    ) -> list[MemoryEntry]:
        """Deserialize memory entries."""
        return [
            self.deserialize_entry(entry_payload) for entry_payload in payload.values()
        ]
