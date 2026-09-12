from dataclasses import dataclass
from datetime import datetime

from ohana_agent.observation.observation_state import ObservationState
from ohana_agent.observation.observer_result import ObserverResult


@dataclass(slots=True)
class ObservationRuntime:
    """Runtime information for an observation."""

    state: ObservationState = ObservationState.IDLE

    last_result: ObserverResult | None = None

    last_execution: datetime | None = None

    next_execution: datetime | None = None
