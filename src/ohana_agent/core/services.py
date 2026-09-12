"""Service registry for Shikamaru core services."""

from typing import TypeVar

T = TypeVar("T")


class ServiceRegistryError(Exception):
    """Base exception for service registry errors."""


class ServiceNotFoundError(ServiceRegistryError):
    """Raised when a requested service is not registered."""


class ServiceAlreadyRegisteredError(ServiceRegistryError):
    """Raised when a service is already registered."""


class ServiceRegistry:
    """Registry used to store and retrieve core services."""

    def __init__(self) -> None:
        self._services: dict[type[object], object] = {}

    def register(self, key: type[T], service: T) -> None:
        """Register a service with its type key."""
        if key in self._services:
            raise ServiceAlreadyRegisteredError(
                f"Service already registered: {key.__name__}"
            )

        self._services[key] = service

    def get(self, key: type[T]) -> T:
        """Retrieve a registered service."""
        if key not in self._services:
            raise ServiceNotFoundError(f"Service not found: {key.__name__}")

        return self._services[key]  # type: ignore[return-value]

    def has(self, key: type[object]) -> bool:
        """Return whether a service is registered."""
        return key in self._services

    def unregister(self, key: type[object]) -> None:
        """Remove a registered service."""
        if key not in self._services:
            raise ServiceNotFoundError(f"Service not found: {key.__name__}")

        del self._services[key]
