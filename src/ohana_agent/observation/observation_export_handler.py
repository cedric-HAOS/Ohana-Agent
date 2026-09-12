"""Observation export event handler."""

from dataclasses import dataclass

from ohana_agent.observation.events import ObservationPublished
from ohana_agent.observation.observation_export_pipeline import (
    ObservationExportPipeline,
)


@dataclass(slots=True)
class ObservationExportHandler:
    """Exports observations received through domain events."""

    pipeline: ObservationExportPipeline

    def handle(
        self,
        event: ObservationPublished,
    ) -> None:
        """Export the observation carried by an event."""
        self.pipeline.export(event.observation)
