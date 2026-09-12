"""Core runtime abstraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Runtime:
    """Base runtime information for a service."""

    started_at: datetime | None = None
    stopped_at: datetime | None = None
