"""Infrastructure root model."""

from dataclasses import dataclass, field
from typing import Any

from ohana_agent.infrastructure.endpoint import Endpoint
from ohana_agent.infrastructure.enums import EndpointType, ServiceType
from ohana_agent.infrastructure.node import Node
from ohana_agent.infrastructure.service import Service


@dataclass(slots=True)
class Infrastructure:
    """Represents the whole supervised infrastructure."""

    name: str
    nodes: list[Node] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: Node) -> None:
        """Attach a node to this infrastructure."""
        self.nodes.append(node)

    def get_node(self, name: str) -> Node | None:
        """Return a node by name."""
        for node in self.nodes:
            if node.name == name:
                return node
        return None

    def find_service(self, service_type: ServiceType) -> Service | None:
        """Return the first service matching the given type."""
        for node in self.nodes:
            service = node.get_service(service_type)
            if service is not None:
                return service
        return None

    def find_services(self, service_type: ServiceType) -> list[Service]:
        """Return all services matching the given type."""
        return [
            service
            for node in self.nodes
            for service in node.services
            if service.type is service_type
        ]

    def find_endpoint(self, address: str) -> Endpoint | None:
        """Return the first endpoint matching the given address."""
        for node in self.nodes:
            endpoint = node.get_endpoint_by_address(address)
            if endpoint is not None:
                return endpoint
        return None

    def find_endpoint_by_type(self, endpoint_type: EndpointType) -> Endpoint | None:
        """Return the first endpoint matching the given type."""
        for node in self.nodes:
            endpoint = node.get_endpoint(endpoint_type)
            if endpoint is not None:
                return endpoint
        return None
