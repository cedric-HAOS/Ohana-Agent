"""Observation exporter contract."""

from abc import ABC, abstractmethod

from ohana_agent.observation.observation import Observation


class ObservationExporter(ABC):
    """Contract implemented by observation exporters."""

    @abstractmethod
    def export(self, observation: Observation) -> None:
        """Export an observation."""
