"""Tests for capability model."""

from ohana_agent.core.capability.base import BaseCapability
from ohana_agent.core.capability.capability import Capability
from ohana_agent.core.capability.capability_health import CapabilityHealth
from ohana_agent.core.capability.capability_state import CapabilityState


def test_capability_implements_base_capability() -> None:
    capability = Capability(
        capability_id="dns",
        name="DNS",
    )

    assert isinstance(capability, BaseCapability)


def test_capability_is_created_with_default_state() -> None:
    capability = Capability(
        capability_id="dns",
        name="DNS",
    )

    assert capability.capability_id == "dns"
    assert capability.name == "DNS"
    assert capability.state == CapabilityState.CREATED
    assert capability.health == CapabilityHealth.UNKNOWN


def test_capability_can_transition_state() -> None:
    capability = Capability(
        capability_id="dns",
        name="DNS",
    )

    capability.transition_to(CapabilityState.READY)

    assert capability.state == CapabilityState.READY


def test_capability_initialize_sets_ready_state() -> None:
    capability = Capability(
        capability_id="dns",
        name="DNS",
    )

    capability.initialize()

    assert capability.state == CapabilityState.READY


def test_capability_start_sets_running_and_healthy() -> None:
    capability = Capability(
        capability_id="dns",
        name="DNS",
    )

    capability.start()

    assert capability.state == CapabilityState.RUNNING
    assert capability.health == CapabilityHealth.HEALTHY


def test_capability_stop_sets_stopped_state() -> None:
    capability = Capability(
        capability_id="dns",
        name="DNS",
    )

    capability.stop()

    assert capability.state == CapabilityState.STOPPED


def test_capability_degrade_sets_warning_health() -> None:
    capability = Capability(
        capability_id="dns",
        name="DNS",
    )

    capability.degrade()

    assert capability.state == CapabilityState.DEGRADED
    assert capability.health == CapabilityHealth.WARNING


def test_capability_fail_sets_critical_health() -> None:
    capability = Capability(
        capability_id="dns",
        name="DNS",
    )

    capability.fail()

    assert capability.state == CapabilityState.ERROR
    assert capability.health == CapabilityHealth.CRITICAL
