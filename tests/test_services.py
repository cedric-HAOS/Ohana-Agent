"""Tests for the Shikamaru service registry."""

import pytest

from ohana_agent.core.services import (
    ServiceAlreadyRegisteredError,
    ServiceNotFoundError,
    ServiceRegistry,
)


class DummyService:
    """Dummy service used for registry tests."""


class AnotherService:
    """Another dummy service used for registry tests."""


def test_register_and_get_service() -> None:
    """A registered service can be retrieved."""
    registry = ServiceRegistry()
    service = DummyService()

    registry.register(DummyService, service)

    assert registry.get(DummyService) is service


def test_has_returns_true_when_service_is_registered() -> None:
    """has() returns True when a service exists."""
    registry = ServiceRegistry()
    service = DummyService()

    registry.register(DummyService, service)

    assert registry.has(DummyService) is True


def test_has_returns_false_when_service_is_not_registered() -> None:
    """has() returns False when a service does not exist."""
    registry = ServiceRegistry()

    assert registry.has(DummyService) is False


def test_get_unknown_service_raises_error() -> None:
    """Getting an unknown service raises ServiceNotFoundError."""
    registry = ServiceRegistry()

    with pytest.raises(ServiceNotFoundError):
        registry.get(DummyService)


def test_register_existing_service_raises_error() -> None:
    """Registering an existing service raises ServiceAlreadyRegisteredError."""
    registry = ServiceRegistry()
    service = DummyService()

    registry.register(DummyService, service)

    with pytest.raises(ServiceAlreadyRegisteredError):
        registry.register(DummyService, service)


def test_unregister_service() -> None:
    """A registered service can be unregistered."""
    registry = ServiceRegistry()
    service = DummyService()

    registry.register(DummyService, service)
    registry.unregister(DummyService)

    assert registry.has(DummyService) is False


def test_unregister_unknown_service_raises_error() -> None:
    """Unregistering an unknown service raises ServiceNotFoundError."""
    registry = ServiceRegistry()

    with pytest.raises(ServiceNotFoundError):
        registry.unregister(DummyService)


def test_multiple_services_can_be_registered() -> None:
    """Multiple services can be registered with different keys."""
    registry = ServiceRegistry()
    dummy_service = DummyService()
    another_service = AnotherService()

    registry.register(DummyService, dummy_service)
    registry.register(AnotherService, another_service)

    assert registry.get(DummyService) is dummy_service
    assert registry.get(AnotherService) is another_service
