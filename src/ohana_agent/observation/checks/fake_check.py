from ohana_agent.observation.checks.base_check import BaseCheck
from ohana_agent.observation.observer_result import ObserverResult


class FakeCheck(BaseCheck):
    """Fake check used for tests."""

    def __init__(
        self,
        result: ObserverResult | None = None,
    ) -> None:
        self._result = result or ObserverResult(
            success=True,
            latency=0.0,
        )

    @property
    def name(self) -> str:
        """Return the check name."""
        return "fake"

    @property
    def description(self) -> str:
        """Return the check description."""
        return "Fake observation check"

    def execute(self) -> ObserverResult:
        """Return the configured fake result."""
        return self._result
