"""Backward-compatible infrastructure observation import."""

from ohana_agent.infrastructure.infrastructure_health_update import (
    InfrastructureHealthUpdate,
)

Observation = InfrastructureHealthUpdate

__all__ = [
    "InfrastructureHealthUpdate",
    "Observation",
]
