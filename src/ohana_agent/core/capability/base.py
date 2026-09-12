"""Base capability contract."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from ohana_agent.core.capability.capability_health import CapabilityHealth
from ohana_agent.core.capability.capability_state import CapabilityState


class BaseCapability(ABC):
    """Abstract base class for all capabilities."""

    @property
    @abstractmethod
    def capability_id(self) -> str:
        """Return the unique capability id."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the capability name."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Return the capability version."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Return the capability description."""

    @property
    @abstractmethod
    def dependencies(self) -> list[str]:
        """Return required dependency ids."""

    @property
    @abstractmethod
    def optional_dependencies(self) -> list[str]:
        """Return optional dependency ids."""

    @property
    @abstractmethod
    def commands(self) -> list[str]:
        """Return command names exposed by the capability."""

    @property
    @abstractmethod
    def events(self) -> list[str]:
        """Return event names published by the capability."""

    @property
    @abstractmethod
    def configuration(self) -> dict[str, Any]:
        """Return capability configuration."""

    @property
    @abstractmethod
    def state(self) -> CapabilityState:
        """Return current capability state."""

    @property
    @abstractmethod
    def health(self) -> CapabilityHealth:
        """Return current capability health."""

    @property
    @abstractmethod
    def last_transition_at(self) -> datetime:
        """Return last state transition datetime."""

    @abstractmethod
    def transition_to(self, state: CapabilityState) -> None:
        """Transition the capability to another state."""

    @abstractmethod
    def set_health(self, health: CapabilityHealth) -> None:
        """Set capability health."""

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the capability."""

    @abstractmethod
    def start(self) -> None:
        """Start the capability."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the capability."""

    @abstractmethod
    def degrade(self) -> None:
        """Mark the capability as degraded."""

    @abstractmethod
    def fail(self) -> None:
        """Mark the capability as failed."""
