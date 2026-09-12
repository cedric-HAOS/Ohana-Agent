"""Recovery engine for Ohana-Agent."""

from __future__ import annotations

from ohana_agent.observation.health.monitor import HealthResult, HealthStatus
from ohana_agent.recovery.result import RecoveryResult
from ohana_agent.recovery.strategy import RecoveryStrategy


class RecoveryEngine:
    """Coordinates recovery attempts for unhealthy components."""

    def __init__(self) -> None:
        self._strategies: list[RecoveryStrategy] = []
        self._recovering: set[str] = set()
        self._history: list[RecoveryResult] = []

    @property
    def history(self) -> list[RecoveryResult]:
        """Return recovery history."""
        return list(self._history)

    def register_strategy(self, strategy: RecoveryStrategy) -> None:
        """Register a recovery strategy."""
        self._strategies.append(strategy)

    def is_recovering(self, source: str) -> bool:
        """Return whether a source is currently recovering."""
        return source in self._recovering

    def handle(self, result: HealthResult) -> RecoveryResult | None:
        """Handle a health result and recover if needed."""
        if result.status not in {HealthStatus.DEGRADED, HealthStatus.UNHEALTHY}:
            return None

        return self.recover(result)

    def recover(self, result: HealthResult) -> RecoveryResult | None:
        """Recover a source from a health result."""
        source = result.name

        if source in self._recovering:
            return None

        strategy = self._find_strategy(result)

        if strategy is None:
            return None

        self._recovering.add(source)

        try:
            recovery_result = strategy.execute(result)
            self._history.append(recovery_result)
            return recovery_result
        finally:
            self._recovering.remove(source)

    def _find_strategy(self, result: HealthResult) -> RecoveryStrategy | None:
        for strategy in self._strategies:
            if strategy.can_handle(result):
                return strategy

        return None
