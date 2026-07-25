"""Runtime state for infrastructure nodes."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from infrastructure.endpoint import Endpoint
from infrastructure.enums import HealthStatus, ServiceType
from infrastructure.node import Node
from infrastructure.runtime.endpoint_runtime import EndpointRuntime
from infrastructure.runtime.service_runtime import ServiceRuntime
from infrastructure.service import Service


@dataclass(slots=True)
class NodeRuntime:
    """Represents the runtime state of a node."""

    node: Node
    health: HealthStatus = HealthStatus.UNKNOWN
    endpoint_runtimes: list[EndpointRuntime] = field(default_factory=list)
    service_runtimes: list[ServiceRuntime] = field(default_factory=list)
    last_update: datetime | None = None

    @classmethod
    def from_node(cls, node: Node) -> "NodeRuntime":
        """Create a node runtime from a node model."""
        return cls(
            node=node,
            endpoint_runtimes=[
                EndpointRuntime(endpoint=endpoint) for endpoint in node.endpoints
            ],
            service_runtimes=[
                ServiceRuntime(service=service) for service in node.services
            ],
        )

    def update_health(self, health: HealthStatus) -> None:
        """Update node health and timestamp."""
        self.health = health
        self.last_update = datetime.now(UTC)

    def get_endpoint_runtime(
        self,
        endpoint: Endpoint,
    ) -> EndpointRuntime | None:
        """Return runtime state associated with an endpoint."""
        for endpoint_runtime in self.endpoint_runtimes:
            if endpoint_runtime.endpoint is endpoint:
                return endpoint_runtime
        return None

    def get_service_runtime(self, service: Service) -> ServiceRuntime | None:
        """Return runtime state associated with a service."""
        for service_runtime in self.service_runtimes:
            if service_runtime.service is service:
                return service_runtime
        return None

    def get_service_runtime_by_name(
        self,
        name: str,
    ) -> ServiceRuntime | None:
        """Return the service runtime matching a stable service identifier."""
        for service_runtime in self.service_runtimes:
            if service_runtime.service.name == name:
                return service_runtime
        return None

    def get_service_runtime_by_type(
        self,
        service_type: ServiceType,
    ) -> ServiceRuntime | None:
        """Return first service runtime matching the given service type."""
        for service_runtime in self.service_runtimes:
            if service_runtime.service.type is service_type:
                return service_runtime
        return None
