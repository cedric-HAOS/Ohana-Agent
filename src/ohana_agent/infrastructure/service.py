"""Infrastructure service model."""

from dataclasses import dataclass, field
from typing import Any

from ohana_agent.infrastructure.endpoint import Endpoint
from ohana_agent.infrastructure.enums import HealthStatus, ServiceType


@dataclass(slots=True)
class Service:
    """Represents a service provided by an infrastructure node."""

    name: str
    type: ServiceType
    endpoint: Endpoint | None = None
    health: HealthStatus = HealthStatus.UNKNOWN
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_enabled(self) -> bool:
        """Return whether this service is enabled."""
        return self.enabled
