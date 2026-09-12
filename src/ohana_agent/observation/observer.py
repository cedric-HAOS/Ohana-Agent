from ohana_agent.observation.checks.base_check import BaseCheck
from ohana_agent.observation.observer_result import ObserverResult
from ohana_agent.observation.observer_runtime import ObserverRuntime


class Observer:
    """Execute observation checks and record their results."""

    def __init__(
        self,
        runtime: ObserverRuntime | None = None,
    ) -> None:
        self.runtime = runtime or ObserverRuntime()

    def observe(self, check: BaseCheck) -> ObserverResult:
        """Execute a check and record its result."""
        result = check.execute()

        self.runtime.record(result)

        return result
