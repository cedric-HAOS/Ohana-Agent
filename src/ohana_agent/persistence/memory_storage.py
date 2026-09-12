"""JSON memory storage."""

from __future__ import annotations

import json
from pathlib import Path

from .memory_entry import MemoryEntry
from .memory_scope import MemoryScope
from .memory_serializer import MemorySerializer


class MemoryStorage:
    """Store persistent memory entries in a JSON file."""

    def __init__(
        self,
        path: str | Path,
        serializer: MemorySerializer | None = None,
    ) -> None:
        """Initialize storage."""
        self._path = Path(path)
        self._serializer = serializer or MemorySerializer()

    def exists(self) -> bool:
        """Return True if storage file exists."""
        return self._path.exists()

    def save(self, entries: list[MemoryEntry]) -> None:
        """Save persistent entries to disk."""
        persistent_entries = [
            entry for entry in entries if entry.scope is MemoryScope.PERSISTENT
        ]

        payload = {
            "entries": self._serializer.serialize_entries(
                persistent_entries,
            ),
        }

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def load(self) -> list[MemoryEntry]:
        """Load persistent entries from disk."""
        if not self.exists():
            return []

        payload = json.loads(
            self._path.read_text(encoding="utf-8"),
        )

        entries = payload.get("entries", {})

        return self._serializer.deserialize_entries(entries)

    def clear(self) -> None:
        """Delete storage file if present."""
        if self.exists():
            self._path.unlink()
