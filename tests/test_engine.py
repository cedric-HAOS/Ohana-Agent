"""Tests for recovery engine."""

from __future__ import annotations

from dataclasses import dataclass

from ohana_agent.observation.health.monitor import HealthResult, HealthStatus
from ohana_agent.recovery.engine import RecoveryEngine
from ohana_agent.recovery.result import RecoveryResult


@dataclass
class DummyRecoveryStrategy:
    """Recovery strategy used in tests."""

    source: str
    success: bool = True

    def can_handle(self, result: HealthResult) -> bool:
        """Return whether this strategy can handle the health result."""
        return result.name == self.source

    def execute(self, result: HealthResult) -> RecoveryResult:
        """Execute the recovery strategy."""
        return RecoveryResult(
            success=self.success,
            action="dummy",
            source=result.name,
            message="Dummy recovery executed.",
        )


def test_engine_does_nothing_for_healthy_result() -> None:
    engine = RecoveryEngine()
    result = HealthResult(name="plugin.dns", status=HealthStatus.HEALTHY)

    recovery_result = engine.handle(result)

    assert recovery_result is None
    assert engine.history == []


def test_engine_does_nothing_for_unknown_result() -> None:
    engine = RecoveryEngine()
    result = HealthResult(name="plugin.dns", status=HealthStatus.UNKNOWN)

    recovery_result = engine.handle(result)

    assert recovery_result is None
    assert engine.history == []


def test_engine_recovers_degraded_result() -> None:
    engine = RecoveryEngine()
    engine.register_strategy(DummyRecoveryStrategy(source="plugin.dns"))

    result = HealthResult(name="plugin.dns", status=HealthStatus.DEGRADED)

    recovery_result = engine.handle(result)

    assert recovery_result == RecoveryResult(
        success=True,
        action="dummy",
        source="plugin.dns",
        message="Dummy recovery executed.",
    )
    assert engine.history == [recovery_result]


def test_engine_recovers_unhealthy_result() -> None:
    engine = RecoveryEngine()
    engine.register_strategy(DummyRecoveryStrategy(source="plugin.dns"))

    result = HealthResult(name="plugin.dns", status=HealthStatus.UNHEALTHY)

    recovery_result = engine.handle(result)

    assert recovery_result is not None
    assert recovery_result.success is True
    assert recovery_result.source == "plugin.dns"


def test_engine_returns_none_when_no_strategy_matches() -> None:
    engine = RecoveryEngine()
    engine.register_strategy(DummyRecoveryStrategy(source="plugin.dhcp"))

    result = HealthResult(name="plugin.dns", status=HealthStatus.UNHEALTHY)

    recovery_result = engine.handle(result)

    assert recovery_result is None
    assert engine.history == []


def test_engine_tracks_failed_recovery_in_history() -> None:
    engine = RecoveryEngine()
    engine.register_strategy(DummyRecoveryStrategy(source="plugin.dns", success=False))

    result = HealthResult(name="plugin.dns", status=HealthStatus.UNHEALTHY)

    recovery_result = engine.handle(result)

    assert recovery_result is not None
    assert recovery_result.success is False
    assert engine.history == [recovery_result]


def test_engine_is_not_recovering_after_recovery_completed() -> None:
    engine = RecoveryEngine()
    engine.register_strategy(DummyRecoveryStrategy(source="plugin.dns"))

    result = HealthResult(name="plugin.dns", status=HealthStatus.UNHEALTHY)

    engine.handle(result)

    assert engine.is_recovering("plugin.dns") is False


def test_engine_returns_copy_of_history() -> None:
    engine = RecoveryEngine()
    engine.register_strategy(DummyRecoveryStrategy(source="plugin.dns"))

    result = HealthResult(name="plugin.dns", status=HealthStatus.UNHEALTHY)

    engine.handle(result)

    history = engine.history
    history.clear()

    assert len(engine.history) == 1
