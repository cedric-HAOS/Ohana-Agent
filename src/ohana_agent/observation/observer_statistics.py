from dataclasses import dataclass

from ohana_agent.observation.observer_result import ObserverResult


@dataclass(slots=True)
class ObserverStatistics:
    """Statistics computed from observer results."""

    observations: int = 0
    successes: int = 0
    failures: int = 0
    total_latency: float = 0.0
    min_latency: float | None = None
    max_latency: float | None = None

    def record(self, result: ObserverResult) -> None:
        """Record a new observation result."""
        self.observations += 1
        self.total_latency += result.latency

        if result.ok:
            self.successes += 1
        else:
            self.failures += 1

        if self.min_latency is None or result.latency < self.min_latency:
            self.min_latency = result.latency

        if self.max_latency is None or result.latency > self.max_latency:
            self.max_latency = result.latency

    @property
    def success_rate(self) -> float:
        """Return the success rate as a percentage."""
        if self.observations == 0:
            return 0.0

        return (self.successes / self.observations) * 100

    @property
    def failure_rate(self) -> float:
        """Return the failure rate as a percentage."""
        if self.observations == 0:
            return 0.0

        return (self.failures / self.observations) * 100

    @property
    def average_latency(self) -> float:
        """Return the average latency."""
        if self.observations == 0:
            return 0.0

        return self.total_latency / self.observations
