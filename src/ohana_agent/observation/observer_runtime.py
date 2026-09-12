from ohana_agent.observation.observer_result import ObserverResult
from ohana_agent.observation.observer_state import ObserverState
from ohana_agent.observation.observer_statistics import ObserverStatistics


class ObserverRuntime:
    """Runtime state and statistics for the observer."""

    def __init__(self) -> None:
        self._state = ObserverState.IDLE
        self._statistics = ObserverStatistics()
        self._last_result: ObserverResult | None = None

    @property
    def state(self) -> ObserverState:
        """Return the current observer state."""
        return self._state

    @property
    def statistics(self) -> ObserverStatistics:
        """Return observer statistics."""
        return self._statistics

    @property
    def last_result(self) -> ObserverResult | None:
        """Return the latest observation result."""
        return self._last_result

    def start(self) -> None:
        """Start the observer runtime."""
        self._state = ObserverState.RUNNING

    def stop(self) -> None:
        """Stop the observer runtime."""
        self._state = ObserverState.STOPPED

    def record(self, result: ObserverResult) -> None:
        """Record an observation result."""
        self._last_result = result
        self._statistics.record(result)
