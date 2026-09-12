"""Ohana-Vision observation exporter."""

from dataclasses import dataclass

from ohana_agent.observation.exporters.vision_client import VisionClient
from ohana_agent.observation.exporters.vision_observation_mapper import (
    VisionObservationMapper,
)
from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_exporter import ObservationExporter


@dataclass(slots=True)
class VisionObservationExporter(ObservationExporter):
    """Export standard observations to Ohana-Vision."""

    client: VisionClient
    mapper: VisionObservationMapper

    def export(self, observation: Observation) -> None:
        """Map and send an observation to Ohana-Vision."""
        payload = self.mapper.to_payload(observation)

        self.client.send_observation(payload)
