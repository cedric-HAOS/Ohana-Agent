"""Default capability implementation."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ohana_agent.core.capability.base import BaseCapability
from ohana_agent.core.capability.capability_health import CapabilityHealth
from ohana_agent.core.capability.capability_state import CapabilityState


@dataclass(slots=True)
class Capability(BaseCapability):
    """Default implementation for an Ohana-Agent capability."""

    capability_id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    dependencies: list[str] = field(default_factory=list)
    optional_dependencies: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    configuration: dict[str, Any] = field(default_factory=dict)
    state: CapabilityState = CapabilityState.CREATED
    health: CapabilityHealth = CapabilityHealth.UNKNOWN
    last_transition_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def transition_to(self, state: CapabilityState) -> None:
        """Transition the capability to another state."""
        self.state = state
        self.last_transition_at = datetime.now(UTC)

    def set_health(self, health: CapabilityHealth) -> None:
        """Set the capability health."""
        self.health = health

    def initialize(self) -> None:
        """Initialize the capability."""
        self.transition_to(CapabilityState.INITIALIZING)
        self.transition_to(CapabilityState.READY)

    def start(self) -> None:
        """Start the capability."""
        self.transition_to(CapabilityState.STARTING)
        self.transition_to(CapabilityState.RUNNING)
        self.set_health(CapabilityHealth.HEALTHY)

    def stop(self) -> None:
        """Stop the capability."""
        self.transition_to(CapabilityState.STOPPING)
        self.transition_to(CapabilityState.STOPPED)

    def degrade(self) -> None:
        """Mark the capability as degraded."""
        self.transition_to(CapabilityState.DEGRADED)
        self.set_health(CapabilityHealth.WARNING)

    def fail(self) -> None:
        """Mark the capability as failed."""
        self.transition_to(CapabilityState.ERROR)
        self.set_health(CapabilityHealth.CRITICAL)
