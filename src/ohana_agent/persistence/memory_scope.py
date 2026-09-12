"""Memory scopes."""

from __future__ import annotations

from enum import Enum, auto


class MemoryScope(Enum):
    """Available memory scopes."""

    RUNTIME = auto()
    SESSION = auto()
    PERSISTENT = auto()
