"""Infrastructure health update model."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ohana_agent.infrastructure.enums import HealthStatus


@dataclass(slots=True)
class InfrastructureHealthUpdate:
    """Represents a health update emitted for an infrastructure target."""

    target_name: str

    health: HealthStatus

    source: str

    message: str = ""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    metadata: dict[str, Any] = field(default_factory=dict)
