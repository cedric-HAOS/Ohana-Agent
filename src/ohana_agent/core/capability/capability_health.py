"""Capability health states."""

from enum import StrEnum


class CapabilityHealth(StrEnum):
    """Health states for a capability."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
