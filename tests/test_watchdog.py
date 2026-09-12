"""Tests for watchdog health checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ohana_agent.observation.health.monitor import HealthStatus
from ohana_agent.observation.health.watchdog import Watchdog, WatchdogRegistry


def test_watchdog_is_unknown_without_heartbeat() -> None:
    watchdog = Watchdog(source="plugin.dns", timeout_seconds=30)
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)

    result = watchdog.check(now)

    assert result.name == "plugin.dns"
    assert result.status == HealthStatus.UNKNOWN


def test_watchdog_is_healthy_with_fresh_heartbeat() -> None:
    watchdog = Watchdog(source="plugin.dns", timeout_seconds=30)
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)

    watchdog.heartbeat(now - timedelta(seconds=10))
    result = watchdog.check(now)

    assert result.status == HealthStatus.HEALTHY


def test_watchdog_is_degraded_after_degraded_threshold() -> None:
    watchdog = Watchdog(
        source="plugin.dns",
        timeout_seconds=30,
        degraded_after_seconds=10,
    )
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)

    watchdog.heartbeat(now - timedelta(seconds=15))
    result = watchdog.check(now)

    assert result.status == HealthStatus.DEGRADED


def test_watchdog_is_unhealthy_after_timeout() -> None:
    watchdog = Watchdog(
        source="plugin.dns",
        timeout_seconds=30,
        degraded_after_seconds=10,
    )
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)

    watchdog.heartbeat(now - timedelta(seconds=31))
    result = watchdog.check(now)

    assert result.status == HealthStatus.UNHEALTHY


def test_registry_registers_watchdog_and_checks_unknown_status() -> None:
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    registry = WatchdogRegistry(now=lambda: now)

    registry.register("plugin.dns", timeout_seconds=30)

    results = registry.check_all()

    assert len(results) == 1
    assert results[0].name == "plugin.dns"
    assert results[0].status == HealthStatus.UNKNOWN


def test_registry_records_heartbeat_for_registered_source() -> None:
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    registry = WatchdogRegistry(now=lambda: now)

    registry.register("plugin.dns", timeout_seconds=30)
    registry.heartbeat("plugin.dns")

    results = registry.check_all()

    assert results[0].status == HealthStatus.HEALTHY


def test_registry_ignores_heartbeat_for_unknown_source() -> None:
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    registry = WatchdogRegistry(now=lambda: now)

    registry.heartbeat("unknown.source")

    assert registry.check_all() == []


def test_registry_rejects_duplicate_watchdog() -> None:
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    registry = WatchdogRegistry(now=lambda: now)

    registry.register("plugin.dns", timeout_seconds=30)

    with pytest.raises(ValueError, match="Watchdog already registered"):
        registry.register("plugin.dns", timeout_seconds=30)
