"""Tests for capability manager."""

import pytest

from ohana_agent.core.capability.base import BaseCapability
from ohana_agent.core.capability.capability import Capability
from ohana_agent.core.capability.capability_health import CapabilityHealth
from ohana_agent.core.capability.capability_manager import CapabilityManager
from ohana_agent.core.capability.capability_state import CapabilityState
from ohana_agent.core.capability.exceptions import (
    CapabilityAlreadyRegisteredError,
    CapabilityDependencyError,
    CapabilityNotFoundError,
)


class FakeCapability(Capability):
    """Fake concrete capability used to validate BaseCapability support."""


def test_manager_registers_base_capability_implementation() -> None:
    manager = CapabilityManager()
    capability: BaseCapability = FakeCapability(
        capability_id="fake",
        name="Fake",
    )

    manager.register(capability)

    assert manager.exists("fake")
    assert manager.get("fake") is capability


def test_manager_registers_capability() -> None:
    manager = CapabilityManager()
    capability = Capability(capability_id="dns", name="DNS")

    manager.register(capability)

    assert manager.exists("dns")
    assert manager.get("dns") is capability
    assert capability.state == CapabilityState.REGISTERED


def test_manager_rejects_duplicate_capability() -> None:
    manager = CapabilityManager()
    capability = Capability(capability_id="dns", name="DNS")

    manager.register(capability)

    with pytest.raises(CapabilityAlreadyRegisteredError):
        manager.register(capability)


def test_manager_raises_when_capability_not_found() -> None:
    manager = CapabilityManager()

    with pytest.raises(CapabilityNotFoundError):
        manager.get("dns")


def test_manager_unregisters_capability() -> None:
    manager = CapabilityManager()
    capability = Capability(capability_id="dns", name="DNS")

    manager.register(capability)
    manager.unregister("dns")

    assert not manager.exists("dns")


def test_manager_lists_capabilities() -> None:
    manager = CapabilityManager()
    dns = Capability(capability_id="dns", name="DNS")
    mqtt = Capability(capability_id="mqtt", name="MQTT")

    manager.register(dns)
    manager.register(mqtt)

    assert manager.list() == [dns, mqtt]


def test_manager_initializes_capability() -> None:
    manager = CapabilityManager()
    capability = Capability(capability_id="dns", name="DNS")

    manager.register(capability)
    manager.initialize("dns")

    assert capability.state == CapabilityState.READY


def test_manager_starts_capability_without_dependencies() -> None:
    manager = CapabilityManager()
    capability = Capability(capability_id="dns", name="DNS")

    manager.register(capability)
    manager.start("dns")

    assert capability.state == CapabilityState.RUNNING
    assert capability.health == CapabilityHealth.HEALTHY


def test_manager_refuses_start_when_dependency_is_missing() -> None:
    manager = CapabilityManager()
    capability = Capability(
        capability_id="home_assistant",
        name="Home Assistant",
        dependencies=["mqtt"],
    )

    manager.register(capability)

    with pytest.raises(CapabilityDependencyError):
        manager.start("home_assistant")


def test_manager_refuses_start_when_dependency_is_not_running() -> None:
    manager = CapabilityManager()
    mqtt = Capability(capability_id="mqtt", name="MQTT")
    home_assistant = Capability(
        capability_id="home_assistant",
        name="Home Assistant",
        dependencies=["mqtt"],
    )

    manager.register(mqtt)
    manager.register(home_assistant)

    with pytest.raises(CapabilityDependencyError):
        manager.start("home_assistant")


def test_manager_starts_capability_when_dependency_is_running() -> None:
    manager = CapabilityManager()
    mqtt = Capability(capability_id="mqtt", name="MQTT")
    home_assistant = Capability(
        capability_id="home_assistant",
        name="Home Assistant",
        dependencies=["mqtt"],
    )

    manager.register(mqtt)
    manager.register(home_assistant)

    manager.start("mqtt")
    manager.start("home_assistant")

    assert home_assistant.state == CapabilityState.RUNNING


def test_manager_stops_capability() -> None:
    manager = CapabilityManager()
    capability = Capability(capability_id="dns", name="DNS")

    manager.register(capability)
    manager.start("dns")
    manager.stop("dns")

    assert capability.state == CapabilityState.STOPPED


def test_manager_restarts_capability() -> None:
    manager = CapabilityManager()
    capability = Capability(capability_id="dns", name="DNS")

    manager.register(capability)
    manager.start("dns")
    manager.restart("dns")

    assert capability.state == CapabilityState.RUNNING


def test_manager_lists_running_capabilities() -> None:
    manager = CapabilityManager()
    dns = Capability(capability_id="dns", name="DNS")
    mqtt = Capability(capability_id="mqtt", name="MQTT")

    manager.register(dns)
    manager.register(mqtt)
    manager.start("dns")

    assert manager.list_running() == [dns]


def test_manager_lists_capabilities_in_error() -> None:
    manager = CapabilityManager()
    dns = Capability(capability_id="dns", name="DNS")
    mqtt = Capability(capability_id="mqtt", name="MQTT")

    manager.register(dns)
    manager.register(mqtt)
    mqtt.fail()

    assert manager.list_in_error() == [mqtt]
