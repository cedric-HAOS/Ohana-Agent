"""Mapper from infrastructure health updates to observations."""

from infrastructure.enums import ServiceType
from infrastructure.infrastructure_health_update import (
    InfrastructureHealthUpdate,
)
from infrastructure.runtime import InfrastructureRuntime
from observer.observation import Observation
from observer.observation_factory import ObservationFactory
from observer.observation_status import ObservationStatus


class InfrastructureObservationMapper:
    """Convert infrastructure health updates into standard observations."""

    def __init__(
        self,
        factory: ObservationFactory | None = None,
    ) -> None:
        self._factory = factory or ObservationFactory()

    def map(
        self,
        update: InfrastructureHealthUpdate,
        *,
        node: str,
        service: str,
        capability: str,
        latency_ms: float | None = None,
    ) -> Observation:
        """Convert an infrastructure health update into an observation."""
        status = ObservationStatus(update.health.value)

        return self._factory.create(
            node=node,
            service=service,
            capability=capability,
            status=status,
            success=status is ObservationStatus.HEALTHY,
            message=update.message,
            source=update.source,
            latency_ms=latency_ms,
            metadata=update.metadata.copy(),
        )

    def map_device_update(
        self,
        update: InfrastructureHealthUpdate,
        *,
        device_id: str,
        capability: str,
        latency_ms: float | None = None,
    ) -> Observation:
        """Map a topology device update without changing runtime health."""
        node_id = update.metadata.get("node_id")
        resolved_node_id = (
            node_id.strip()
            if isinstance(node_id, str) and node_id.strip()
            else device_id
        )
        metadata = update.metadata.copy()
        metadata.setdefault("target_type", "device")
        metadata.setdefault("device_id", device_id)
        status = ObservationStatus(update.health.value)

        return self._factory.create(
            node=resolved_node_id,
            service=device_id,
            capability=capability,
            status=status,
            success=status is ObservationStatus.HEALTHY,
            message=update.message,
            source=update.source,
            latency_ms=latency_ms,
            metadata=metadata,
        )

    def map_service_update(
        self,
        runtime: InfrastructureRuntime,
        update: InfrastructureHealthUpdate,
        *,
        capability: str,
        latency_ms: float | None = None,
    ) -> Observation:
        """Map a service health update using infrastructure runtime context."""
        service_runtime = runtime.get_service_runtime_by_name(update.target_name)

        if service_runtime is None:
            try:
                service_type = ServiceType(update.target_name)
            except ValueError as error:
                raise ValueError(
                    f"Unknown infrastructure service target: {update.target_name!r}."
                ) from error

            service_runtime = runtime.get_service_runtime_by_type(service_type)

            if service_runtime is None:
                raise LookupError(
                    f"No runtime found for service type {service_type.value!r}."
                )

        node_runtime = runtime.get_node_runtime_for_service(service_runtime.service)

        if node_runtime is None:
            raise LookupError(
                f"No node runtime found for service {service_runtime.service.name!r}."
            )

        return self.map(
            update,
            node=node_runtime.node.name,
            service=service_runtime.service.name,
            capability=capability,
            latency_ms=latency_ms,
        )
