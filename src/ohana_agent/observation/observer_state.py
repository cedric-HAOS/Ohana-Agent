from enum import Enum


class ObserverState(Enum):
    """State of the observer runtime."""

    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
