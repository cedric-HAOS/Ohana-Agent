"""Bridge between scheduler executions and infrastructure observations."""

from dataclasses import dataclass

from ohana_agent.infrastructure.enums import HealthStatus
from ohana_agent.infrastructure.infrastructure_health_update import (
    InfrastructureHealthUpdate,
)
from ohana_agent.infrastructure.observation_manager import ObservationManager


@dataclass(slots=True)
class SchedulerObservationHandler:
    """Converts scheduler results into infrastructure observations."""

    observation_manager: ObservationManager

    def handle_success(
        self,
        target_name: str,
        source: str,
        message: str = "",
    ) -> bool:
        """Record a successful scheduler observation."""
        observation = InfrastructureHealthUpdate(
            target_name=target_name,
            health=HealthStatus.HEALTHY,
            source=source,
            message=message,
        )
        return self.observation_manager.record(observation)

    def handle_failure(
        self,
        target_name: str,
        source: str,
        message: str = "",
    ) -> bool:
        """Record a failed scheduler observation."""
        observation = InfrastructureHealthUpdate(
            target_name=target_name,
            health=HealthStatus.UNHEALTHY,
            source=source,
            message=message,
        )
        return self.observation_manager.record(observation)

    def handle_degraded(
        self,
        target_name: str,
        source: str,
        message: str = "",
    ) -> bool:
        """Record a degraded scheduler observation."""
        observation = InfrastructureHealthUpdate(
            target_name=target_name,
            health=HealthStatus.DEGRADED,
            source=source,
            message=message,
        )
        return self.observation_manager.record(observation)
