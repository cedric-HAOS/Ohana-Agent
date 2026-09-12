"""Heartbeat model for health monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Heartbeat:
    """Represents an activity signal from a monitored source."""

    source: str
    timestamp: datetime
    metadata: dict[str, Any] | None = None
