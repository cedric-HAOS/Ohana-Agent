"""Tests for capability dependency graph."""

import pytest

from ohana_agent.core.capability.capability import Capability
from ohana_agent.core.capability.capability_manager import CapabilityManager
from ohana_agent.core.capability.exceptions import (
    CapabilityDependencyCycleError,
    CapabilityDependencyError,
)


def test_dependency_order_without_dependencies() -> None:
    manager = CapabilityManager()

    manager.register(Capability(capability_id="dns", name="DNS"))
    manager.register(Capability(capability_id="mqtt", name="MQTT"))

    assert manager.dependency_order() == ["dns", "mqtt"]


def test_dependency_order_with_single_dependency() -> None:
    manager = CapabilityManager()

    manager.register(Capability(capability_id="mqtt", name="MQTT"))
    manager.register(
        Capability(
            capability_id="home_assistant",
            name="Home Assistant",
            dependencies=["mqtt"],
        )
    )

    assert manager.dependency_order() == ["mqtt", "home_assistant"]


def test_dependency_order_with_multiple_dependencies() -> None:
    manager = CapabilityManager()

    manager.register(Capability(capability_id="network", name="Network"))
    manager.register(
        Capability(
            capability_id="dns",
            name="DNS",
            dependencies=["network"],
        )
    )
    manager.register(
        Capability(
            capability_id="mqtt",
            name="MQTT",
            dependencies=["network"],
        )
    )
    manager.register(
        Capability(
            capability_id="monitoring",
            name="Monitoring",
            dependencies=["dns", "mqtt"],
        )
    )

    assert manager.dependency_order() == [
        "network",
        "dns",
        "mqtt",
        "monitoring",
    ]


def test_reverse_dependency_order() -> None:
    manager = CapabilityManager()

    manager.register(Capability(capability_id="network", name="Network"))
    manager.register(
        Capability(
            capability_id="mqtt",
            name="MQTT",
            dependencies=["network"],
        )
    )
    manager.register(
        Capability(
            capability_id="home_assistant",
            name="Home Assistant",
            dependencies=["mqtt"],
        )
    )

    assert manager.reverse_dependency_order() == [
        "home_assistant",
        "mqtt",
        "network",
    ]


def test_dependency_order_rejects_missing_dependency() -> None:
    manager = CapabilityManager()

    manager.register(
        Capability(
            capability_id="home_assistant",
            name="Home Assistant",
            dependencies=["mqtt"],
        )
    )

    with pytest.raises(CapabilityDependencyError):
        manager.dependency_order()


def test_dependency_order_detects_cycle() -> None:
    manager = CapabilityManager()

    manager.register(
        Capability(
            capability_id="a",
            name="A",
            dependencies=["c"],
        )
    )
    manager.register(
        Capability(
            capability_id="b",
            name="B",
            dependencies=["a"],
        )
    )
    manager.register(
        Capability(
            capability_id="c",
            name="C",
            dependencies=["b"],
        )
    )

    with pytest.raises(CapabilityDependencyCycleError):
        manager.dependency_order()


def test_optional_dependencies_do_not_block_dependency_order() -> None:
    manager = CapabilityManager()

    manager.register(
        Capability(
            capability_id="monitoring",
            name="Monitoring",
            optional_dependencies=["home_assistant"],
        )
    )

    assert manager.dependency_order() == ["monitoring"]
