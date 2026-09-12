"""Recovery result model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecoveryResult:
    """Represents the result of a recovery attempt."""

    success: bool
    action: str
    source: str
    message: str | None = None
    details: dict[str, Any] | None = None
