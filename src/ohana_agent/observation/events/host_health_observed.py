"""Host health observation event, consumed by Tsunade only."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ohana_agent.observation.observation import Observation


@dataclass(frozen=True, slots=True)
class HostHealthObserved:
    """A host.health observation of the Agent's own host.

    Kept apart from ObservationPublished: the Vision and Home Assistant exports
    already receive host health directly, and the Home Assistant summary must
    not count the host as an infrastructure service.
    """

    observation: Observation

    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
