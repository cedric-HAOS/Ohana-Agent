from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from infrastructure.enums import HealthStatus


@dataclass(slots=True)
class ObserverResult:
    """Generic result returned by an observation check."""

    success: bool
    latency: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    message: str | None = None
    check: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    health: HealthStatus | None = None

    @property
    def ok(self) -> bool:
        """Return True when the observation succeeded."""
        return self.success

    @property
    def failed(self) -> bool:
        """Return True when the observation failed."""
        return not self.success
