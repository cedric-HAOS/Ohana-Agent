from enum import Enum


class ObservationState(Enum):
    """State of an observation."""

    IDLE = "idle"
    RUNNING = "running"
    DISABLED = "disabled"
