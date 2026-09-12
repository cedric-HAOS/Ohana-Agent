"""In-memory observation exporter."""

from dataclasses import dataclass, field

from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_exporter import ObservationExporter


@dataclass(slots=True)
class InMemoryObservationExporter(ObservationExporter):
    """Stores exported observations in memory."""

    observations: list[Observation] = field(default_factory=list)

    def export(self, observation: Observation) -> None:
        """Store an observation in memory."""
        self.observations.append(observation)

    def latest(self) -> Observation | None:
        """Return the most recently exported observation."""
        if not self.observations:
            return None

        return self.observations[-1]
