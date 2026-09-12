"""
Ohana-Agent

Component:
    Lifecycle tests

Description:
    Tests the application lifecycle state machine.

Author:
    Cédric Harnois, ChatGPT
"""

from __future__ import annotations

import pytest

from ohana_agent.core.lifecycle import (
    AgentState,
    InvalidStateTransitionError,
    Lifecycle,
)


def test_initial_state_is_created() -> None:
    """A new Lifecycle starts in the CREATED state."""
    lifecycle = Lifecycle()

    assert lifecycle.state == AgentState.CREATED


def test_valid_transition_from_created_to_initializing() -> None:
    """CREATED -> INITIALIZING is allowed."""
    lifecycle = Lifecycle()

    lifecycle.transition_to(AgentState.INITIALIZING)

    assert lifecycle.state == AgentState.INITIALIZING


def test_valid_full_lifecycle_transition() -> None:
    """A complete lifecycle reaches the STOPPED state."""
    lifecycle = Lifecycle()

    lifecycle.transition_to(AgentState.INITIALIZING)
    lifecycle.transition_to(AgentState.READY)
    lifecycle.transition_to(AgentState.RUNNING)
    lifecycle.transition_to(AgentState.STOPPING)
    lifecycle.transition_to(AgentState.STOPPED)

    assert lifecycle.state == AgentState.STOPPED


def test_invalid_transition_raises_error() -> None:
    """An invalid transition raises an explicit exception."""
    lifecycle = Lifecycle()

    with pytest.raises(InvalidStateTransitionError) as exc:
        lifecycle.transition_to(AgentState.RUNNING)

    assert str(exc.value) == "Invalid state transition: CREATED -> RUNNING"


def test_can_transition_to_returns_true_for_valid_transition() -> None:
    """can_transition_to() returns True for valid transitions."""
    lifecycle = Lifecycle()

    assert lifecycle.can_transition_to(AgentState.INITIALIZING) is True


def test_can_transition_to_returns_false_for_invalid_transition() -> None:
    """can_transition_to() returns False for invalid transitions."""
    lifecycle = Lifecycle()

    assert lifecycle.can_transition_to(AgentState.RUNNING) is False


def test_error_transition_is_allowed_from_any_active_state() -> None:
    """ERROR is reachable from every active lifecycle state."""
    lifecycle = Lifecycle()

    active_states = (
        AgentState.CREATED,
        AgentState.INITIALIZING,
        AgentState.READY,
        AgentState.RUNNING,
        AgentState.STOPPING,
    )

    for state in active_states:
        lifecycle = Lifecycle()

        while lifecycle.state != state:
            match lifecycle.state:
                case AgentState.CREATED:
                    lifecycle.transition_to(AgentState.INITIALIZING)

                case AgentState.INITIALIZING:
                    lifecycle.transition_to(AgentState.READY)

                case AgentState.READY:
                    lifecycle.transition_to(AgentState.RUNNING)

                case AgentState.RUNNING:
                    lifecycle.transition_to(AgentState.STOPPING)

                case _:
                    break

        assert lifecycle.can_transition_to(AgentState.ERROR)


def test_state_property_is_read_only() -> None:
    """The state property is read-only."""
    lifecycle = Lifecycle()

    with pytest.raises(AttributeError):
        lifecycle.state = AgentState.RUNNING
