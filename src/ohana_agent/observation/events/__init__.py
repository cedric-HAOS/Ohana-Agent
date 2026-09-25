"""Observation domain events."""

from ohana_agent.observation.events.host_health_observed import HostHealthObserved
from ohana_agent.observation.events.observation_published import ObservationPublished

__all__ = [
    "HostHealthObserved",
    "ObservationPublished",
]
