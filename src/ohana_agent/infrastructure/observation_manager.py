"""Backward-compatible infrastructure observation manager."""

from ohana_agent.infrastructure.infrastructure_health_manager import (
    InfrastructureHealthManager,
)

ObservationManager = InfrastructureHealthManager

__all__ = [
    "InfrastructureHealthManager",
    "ObservationManager",
]
