"""Infrastructure health manager."""

from dataclasses import dataclass, field

from infrastructure.enums import ServiceType
from infrastructure.infrastructure_health_update import (
    InfrastructureHealthUpdate,
)
from infrastructure.runtime import InfrastructureRuntime


@dataclass(slots=True)
class InfrastructureHealthManager:
    """Applies health updates to infrastructure runtime objects."""

    runtime: InfrastructureRuntime

    observations: list[InfrastructureHealthUpdate] = field(default_factory=list)

    def record(
        self,
        observation: InfrastructureHealthUpdate,
    ) -> bool:
        self.observations.append(observation)

        if self._apply_to_service(observation):
            return True

        if self._apply_to_node(observation):
            return True

        return False

    def _apply_to_service(
        self,
        observation: InfrastructureHealthUpdate,
    ) -> bool:
        service_runtime = self.runtime.get_service_runtime_by_name(
            observation.target_name
        )

        if service_runtime is None:
            try:
                service_type = ServiceType(observation.target_name)
            except ValueError:
                return False

            service_runtime = self.runtime.get_service_runtime_by_type(service_type)

        if service_runtime is None:
            return False

        service_runtime.update_health(observation.health)

        return True

    def _apply_to_node(
        self,
        observation: InfrastructureHealthUpdate,
    ) -> bool:
        node_runtime = self.runtime.get_node_runtime_by_name(observation.target_name)

        if node_runtime is None:
            return False

        node_runtime.update_health(observation.health)

        return True
