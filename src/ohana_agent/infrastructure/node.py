"""Infrastructure node model."""

from dataclasses import dataclass, field
from typing import Any

from ohana_agent.infrastructure.endpoint import Endpoint
from ohana_agent.infrastructure.enums import EndpointType, ServiceType
from ohana_agent.infrastructure.service import Service


@dataclass(slots=True)
class Node:
    """Represents a physical or logical infrastructure node."""

    name: str
    description: str = ""
    enabled: bool = True
    endpoints: list[Endpoint] = field(default_factory=list)
    services: list[Service] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_enabled(self) -> bool:
        """Return whether this node is enabled."""
        return self.enabled

    def add_endpoint(self, endpoint: Endpoint) -> None:
        """Attach an endpoint to this node."""
        self.endpoints.append(endpoint)

    def add_service(self, service: Service) -> None:
        """Attach a service to this node."""
        self.services.append(service)

    def get_endpoint(self, endpoint_type: EndpointType) -> Endpoint | None:
        """Return the first endpoint matching the given type."""
        for endpoint in self.endpoints:
            if endpoint.type is endpoint_type:
                return endpoint
        return None

    def get_endpoint_by_address(self, address: str) -> Endpoint | None:
        """Return the first endpoint matching the given address."""
        for endpoint in self.endpoints:
            if endpoint.address == address:
                return endpoint
        return None

    def get_service(self, service_type: ServiceType) -> Service | None:
        """Return the first service matching the given type."""
        for service in self.services:
            if service.type is service_type:
                return service
        return None

    def get_service_by_name(self, name: str) -> Service | None:
        """Return the first service matching the given name."""
        for service in self.services:
            if service.name == name:
                return service
        return None
