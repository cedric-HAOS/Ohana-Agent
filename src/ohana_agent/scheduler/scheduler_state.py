"""Scheduler runtime states."""

from enum import StrEnum


class SchedulerState(StrEnum):
    """Possible runtime states for the scheduler."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
