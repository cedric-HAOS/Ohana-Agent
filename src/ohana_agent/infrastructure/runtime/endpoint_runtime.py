"""Runtime state for infrastructure endpoints."""

from dataclasses import dataclass
from datetime import UTC, datetime

from ohana_agent.infrastructure.endpoint import Endpoint
from ohana_agent.infrastructure.enums import HealthStatus


@dataclass(slots=True)
class EndpointRuntime:
    """Represents the runtime state of an endpoint."""

    endpoint: Endpoint
    health: HealthStatus = HealthStatus.UNKNOWN
    last_update: datetime | None = None

    def update_health(self, health: HealthStatus) -> None:
        """Update endpoint health and timestamp."""
        self.health = health
        self.last_update = datetime.now(UTC)
