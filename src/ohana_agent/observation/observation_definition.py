from dataclasses import dataclass, field
from datetime import timedelta

from ohana_agent.observation.checks.base_check import BaseCheck
from ohana_agent.observation.observation_runtime import ObservationRuntime


@dataclass(slots=True)
class ObservationDefinition:
    """Observation definition."""

    id: str

    display_name: str

    check: BaseCheck

    interval: timedelta = timedelta(minutes=1)

    enabled: bool = True

    timeout: timedelta = timedelta(seconds=5)

    retries: int = 0

    runtime: ObservationRuntime = field(default_factory=ObservationRuntime)
