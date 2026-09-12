"""Tests for recovery strategies."""

from __future__ import annotations

from ohana_agent.observation.health.monitor import HealthResult, HealthStatus
from ohana_agent.recovery.action import NoopRecoveryAction
from ohana_agent.recovery.strategy import StaticRecoveryStrategy


def test_static_strategy_matches_source_and_default_statuses() -> None:
    action = NoopRecoveryAction(name="noop", source="plugin.dns")
    strategy = StaticRecoveryStrategy(source="plugin.dns", action=action)

    assert strategy.can_handle(
        HealthResult(name="plugin.dns", status=HealthStatus.DEGRADED),
    )
    assert strategy.can_handle(
        HealthResult(name="plugin.dns", status=HealthStatus.UNHEALTHY),
    )


def test_static_strategy_rejects_healthy_and_unknown_statuses() -> None:
    action = NoopRecoveryAction(name="noop", source="plugin.dns")
    strategy = StaticRecoveryStrategy(source="plugin.dns", action=action)

    assert not strategy.can_handle(
        HealthResult(name="plugin.dns", status=HealthStatus.HEALTHY),
    )
    assert not strategy.can_handle(
        HealthResult(name="plugin.dns", status=HealthStatus.UNKNOWN),
    )


def test_static_strategy_rejects_different_source() -> None:
    action = NoopRecoveryAction(name="noop", source="plugin.dns")
    strategy = StaticRecoveryStrategy(source="plugin.dns", action=action)

    assert not strategy.can_handle(
        HealthResult(name="plugin.dhcp", status=HealthStatus.UNHEALTHY),
    )


def test_static_strategy_accepts_custom_statuses() -> None:
    action = NoopRecoveryAction(name="noop", source="plugin.dns")
    strategy = StaticRecoveryStrategy(
        source="plugin.dns",
        action=action,
        statuses={HealthStatus.UNHEALTHY},
    )

    assert strategy.can_handle(
        HealthResult(name="plugin.dns", status=HealthStatus.UNHEALTHY),
    )
    assert not strategy.can_handle(
        HealthResult(name="plugin.dns", status=HealthStatus.DEGRADED),
    )


def test_static_strategy_executes_configured_action() -> None:
    action = NoopRecoveryAction(
        name="noop",
        source="plugin.dns",
        message="Recovery noop executed.",
    )
    strategy = StaticRecoveryStrategy(source="plugin.dns", action=action)

    result = strategy.execute(
        HealthResult(name="plugin.dns", status=HealthStatus.UNHEALTHY),
    )

    assert result.success is True
    assert result.action == "noop"
    assert result.source == "plugin.dns"
    assert result.message == "Recovery noop executed."
