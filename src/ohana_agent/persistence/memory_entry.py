"""Memory entry model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .memory_scope import MemoryScope


@dataclass(slots=True)
class MemoryEntry:
    """Represents a value stored in memory."""

    key: str
    value: Any
    scope: MemoryScope = MemoryScope.RUNTIME
