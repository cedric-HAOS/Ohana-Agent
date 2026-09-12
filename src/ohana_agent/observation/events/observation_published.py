"""Observation published event."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ohana_agent.observation.observation import Observation


@dataclass(frozen=True, slots=True)
class ObservationPublished:
    """Event emitted when a standard observation is published."""

    observation: Observation

    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
