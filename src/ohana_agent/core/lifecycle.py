"""
Ohana-Agent

Component:
    Lifecycle

Description:
    Manages the application lifecycle state.

Author:
    Cédric Harnois, ChatGPT
"""

from __future__ import annotations

from enum import Enum


class AgentState(Enum):
    """Available lifecycle states for the application."""

    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class InvalidStateTransitionError(Exception):
    """Raised when an invalid lifecycle transition is requested."""


class Lifecycle:
    """Manages the application lifecycle state."""

    _ALLOWED_TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
        AgentState.CREATED: frozenset({AgentState.INITIALIZING, AgentState.ERROR}),
        AgentState.INITIALIZING: frozenset({AgentState.READY, AgentState.ERROR}),
        AgentState.READY: frozenset(
            {AgentState.RUNNING, AgentState.STOPPING, AgentState.ERROR}
        ),
        AgentState.RUNNING: frozenset({AgentState.STOPPING, AgentState.ERROR}),
        AgentState.STOPPING: frozenset({AgentState.STOPPED, AgentState.ERROR}),
        AgentState.STOPPED: frozenset(),
        AgentState.ERROR: frozenset({AgentState.STOPPING}),
    }

    def __init__(self) -> None:
        self._state: AgentState = AgentState.CREATED

    @property
    def state(self) -> AgentState:
        """Return the current lifecycle state."""
        return self._state

    def can_transition_to(self, new_state: AgentState) -> bool:
        """Return True if the requested transition is allowed."""
        return new_state in self._ALLOWED_TRANSITIONS[self._state]

    def transition_to(self, new_state: AgentState) -> None:
        """Transition to a new lifecycle state."""
        if not self.can_transition_to(new_state):
            raise InvalidStateTransitionError(
                f"Invalid state transition: {self._state.value} -> {new_state.value}"
            )

        self._state = new_state
