"""Runtime state for infrastructure services."""

from dataclasses import dataclass
from datetime import UTC, datetime

from ohana_agent.infrastructure.enums import HealthStatus
from ohana_agent.infrastructure.service import Service


@dataclass(slots=True)
class ServiceRuntime:
    """Represents the runtime state of a service."""

    service: Service
    health: HealthStatus = HealthStatus.UNKNOWN
    last_update: datetime | None = None

    def update_health(self, health: HealthStatus) -> None:
        """Update service health and timestamp."""
        self.health = health
        self.last_update = datetime.now(UTC)
