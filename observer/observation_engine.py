"""Observation engine."""

from dataclasses import dataclass

from infrastructure.infrastructure_health_manager import (
    InfrastructureHealthManager,
)
from infrastructure.infrastructure_health_update import (
    InfrastructureHealthUpdate,
)
from observer.events import ObservationPublished
from observer.infrastructure_observation_mapper import (
    InfrastructureObservationMapper,
)
from observer.observation_event_publisher import (
    ObservationEventPublisher,
)
from observer.observer_result import ObserverResult
from observer.observer_result_mapper import ObserverResultMapper


@dataclass(slots=True)
class ObservationEngine:
    """Orchestrates infrastructure updates and observation publication."""

    health_manager: InfrastructureHealthManager
    mapper: InfrastructureObservationMapper
    result_mapper: ObserverResultMapper
    publisher: ObservationEventPublisher

    def process_result(
        self,
        result: ObserverResult,
        *,
        target_name: str,
        source: str | None = None,
    ) -> ObservationPublished:
        """Process and publish an observer result for a service target."""
        update = self.result_mapper.map(
            result,
            target_name=target_name,
            source=source,
        )

        capability = source or result.check

        if not capability:
            raise ValueError(
                "ObserverResult must define a check or an explicit source."
            )

        if result.metadata.get("target_type") == "device":
            return self.process_device_update(
                update,
                device_id=target_name,
                capability=capability,
                latency_ms=result.latency,
            )

        return self.process_service_update(
            update,
            capability=capability,
            latency_ms=result.latency,
        )

    def process_device_update(
        self,
        update: InfrastructureHealthUpdate,
        *,
        device_id: str,
        capability: str,
        latency_ms: float | None = None,
    ) -> ObservationPublished:
        """Publish a topology presence update outside global health."""
        observation = self.mapper.map_device_update(
            update,
            device_id=device_id,
            capability=capability,
            latency_ms=latency_ms,
        )

        return self.publisher.publish(observation)

    def process_service_update(
        self,
        update: InfrastructureHealthUpdate,
        *,
        capability: str,
        latency_ms: float | None = None,
    ) -> ObservationPublished:
        """Process and publish an infrastructure service health update."""
        applied = self.health_manager.record(update)

        if not applied:
            raise LookupError(
                f"Unable to apply infrastructure health update "
                f"for target {update.target_name!r}."
            )

        observation = self.mapper.map_service_update(
            self.health_manager.runtime,
            update,
            capability=capability,
            latency_ms=latency_ms,
        )

        return self.publisher.publish(observation)
