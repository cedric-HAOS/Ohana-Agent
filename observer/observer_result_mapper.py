"""Mapper from observer results to infrastructure health updates."""

from infrastructure.enums import HealthStatus
from infrastructure.infrastructure_health_update import (
    InfrastructureHealthUpdate,
)
from observer.observer_result import ObserverResult


class ObserverResultMapper:
    """Convert observer results into infrastructure health updates."""

    def map(
        self,
        result: ObserverResult,
        *,
        target_name: str,
        source: str | None = None,
    ) -> InfrastructureHealthUpdate:
        """Convert an observer result into an infrastructure health update."""
        if not target_name:
            raise ValueError("target_name must not be empty.")

        health = (
            result.health
            if result.health is not None
            else (
                HealthStatus.HEALTHY
                if result.success
                else HealthStatus.UNHEALTHY
            )
        )

        resolved_source = source or result.check

        if not resolved_source:
            raise ValueError(
                "ObserverResult must define a check or an explicit source."
            )

        return InfrastructureHealthUpdate(
            target_name=target_name,
            health=health,
            source=resolved_source,
            message=result.message or "",
            timestamp=result.timestamp,
            metadata=result.metadata.copy(),
        )
