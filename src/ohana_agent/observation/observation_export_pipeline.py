"""Observation export pipeline."""

from dataclasses import dataclass, field

from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_exporter import ObservationExporter


@dataclass(slots=True)
class ObservationExportPipeline:
    """Exports observations through multiple exporters."""

    exporters: list[ObservationExporter] = field(default_factory=list)

    def add_exporter(
        self,
        exporter: ObservationExporter,
    ) -> None:
        """Add an exporter to the pipeline."""
        self.exporters.append(exporter)

    def remove_exporter(
        self,
        exporter: ObservationExporter,
    ) -> bool:
        """Remove an exporter from the pipeline."""
        try:
            self.exporters.remove(exporter)
        except ValueError:
            return False

        return True

    def export(
        self,
        observation: Observation,
    ) -> None:
        """Export an observation through every registered exporter."""
        for exporter in self.exporters:
            exporter.export(observation)
