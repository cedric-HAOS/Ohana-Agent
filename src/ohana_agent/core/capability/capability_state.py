"""Capability lifecycle states."""

from enum import StrEnum


class CapabilityState(StrEnum):
    """Lifecycle states for a capability."""

    CREATED = "created"
    REGISTERED = "registered"
    INITIALIZING = "initializing"
    READY = "ready"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
