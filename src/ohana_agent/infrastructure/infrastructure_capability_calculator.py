"""Calculated infrastructure capabilities."""

from dataclasses import dataclass

from ohana_agent.infrastructure.enums import HealthStatus, ServiceType
from ohana_agent.infrastructure.runtime import InfrastructureRuntime


@dataclass(frozen=True, slots=True)
class InfrastructureCapability:
    """Represents a calculated infrastructure capability."""

    name: str
    available: bool
    health: HealthStatus
    reason: str = ""


@dataclass(slots=True)
class InfrastructureCapabilityCalculator:
    """Calculates infrastructure capabilities from runtime state."""

    runtime: InfrastructureRuntime

    def calculate_dns_available(self) -> InfrastructureCapability:
        """Calculate whether DNS is currently available."""
        return self._calculate_service_available(
            capability_name="dns_available",
            service_type=ServiceType.DNS,
        )

    def calculate_mqtt_available(self) -> InfrastructureCapability:
        """Calculate whether MQTT is currently available."""
        return self._calculate_service_available(
            capability_name="mqtt_available",
            service_type=ServiceType.MQTT,
        )

    def _calculate_service_available(
        self,
        capability_name: str,
        service_type: ServiceType,
    ) -> InfrastructureCapability:
        """Calculate whether a service type is currently available."""
        service_runtime = self.runtime.get_service_runtime_by_type(service_type)

        if service_runtime is None:
            return InfrastructureCapability(
                name=capability_name,
                available=False,
                health=HealthStatus.UNKNOWN,
                reason=f"No {service_type.value} service runtime found.",
            )

        if service_runtime.health is HealthStatus.HEALTHY:
            return InfrastructureCapability(
                name=capability_name,
                available=True,
                health=HealthStatus.HEALTHY,
                reason=f"{service_type.value} service is healthy.",
            )

        return InfrastructureCapability(
            name=capability_name,
            available=False,
            health=service_runtime.health,
            reason=f"{service_type.value} service is {service_runtime.health.value}.",
        )
