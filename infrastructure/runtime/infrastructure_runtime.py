"""Runtime state for the whole infrastructure."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from infrastructure.enums import HealthStatus, ServiceType
from infrastructure.infrastructure import Infrastructure
from infrastructure.node import Node
from infrastructure.runtime.node_runtime import NodeRuntime
from infrastructure.runtime.service_runtime import ServiceRuntime
from infrastructure.service import Service


@dataclass(slots=True)
class InfrastructureRuntime:
    """Represents the runtime state of the whole infrastructure."""

    infrastructure: Infrastructure
    health: HealthStatus = HealthStatus.UNKNOWN
    node_runtimes: list[NodeRuntime] = field(default_factory=list)
    last_update: datetime | None = None

    @classmethod
    def from_infrastructure(
        cls,
        infrastructure: Infrastructure,
    ) -> "InfrastructureRuntime":
        """Create an infrastructure runtime from an infrastructure model."""
        return cls(
            infrastructure=infrastructure,
            node_runtimes=[
                NodeRuntime.from_node(node) for node in infrastructure.nodes
            ],
        )

    def update_health(self, health: HealthStatus) -> None:
        """Update infrastructure health and timestamp."""
        self.health = health
        self.last_update = datetime.now(UTC)

    def get_node_runtime(self, node: Node) -> NodeRuntime | None:
        """Return runtime state associated with a node."""
        for node_runtime in self.node_runtimes:
            if node_runtime.node is node:
                return node_runtime
        return None

    def get_node_runtime_by_name(self, name: str) -> NodeRuntime | None:
        """Return runtime state associated with a node name."""
        for node_runtime in self.node_runtimes:
            if node_runtime.node.name == name:
                return node_runtime
        return None

    def get_node_runtime_for_service(
        self,
        service: Service,
    ) -> NodeRuntime | None:
        """Return the node runtime containing the given service."""
        for node_runtime in self.node_runtimes:
            if node_runtime.get_service_runtime(service) is not None:
                return node_runtime

        return None

    def get_node_runtime_for_service_type(
        self,
        service_type: ServiceType,
    ) -> NodeRuntime | None:
        """Return the first node runtime providing a service type."""
        for node_runtime in self.node_runtimes:
            service_runtime = node_runtime.get_service_runtime_by_type(service_type)

            if service_runtime is not None:
                return node_runtime

        return None

    def get_service_runtime(self, service: Service) -> ServiceRuntime | None:
        """Return runtime state associated with a service."""
        for node_runtime in self.node_runtimes:
            service_runtime = node_runtime.get_service_runtime(service)
            if service_runtime is not None:
                return service_runtime
        return None

    def get_service_runtime_by_name(
        self,
        name: str,
    ) -> ServiceRuntime | None:
        """Return the service runtime matching a stable service identifier."""
        for node_runtime in self.node_runtimes:
            service_runtime = node_runtime.get_service_runtime_by_name(name)
            if service_runtime is not None:
                return service_runtime
        return None

    def get_service_runtime_by_type(
        self,
        service_type: ServiceType,
    ) -> ServiceRuntime | None:
        """Return first service runtime matching the given service type."""
        for node_runtime in self.node_runtimes:
            service_runtime = node_runtime.get_service_runtime_by_type(service_type)
            if service_runtime is not None:
                return service_runtime
        return None
