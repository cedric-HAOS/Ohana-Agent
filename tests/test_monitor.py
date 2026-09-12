"""Tests for the health monitor."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ohana_agent.observation.health.monitor import (
    HealthMonitor,
    HealthResult,
    HealthStatus,
)


@dataclass
class DummyHealthCheck:
    """Simple health check used for tests."""

    name: str
    status: HealthStatus

    def run(self) -> HealthResult:
        """Return a fixed health result."""
        return HealthResult(name=self.name, status=self.status)


def test_monitor_status_is_unknown_without_checks() -> None:
    monitor = HealthMonitor()

    assert monitor.get_status() == HealthStatus.UNKNOWN


def test_monitor_registers_and_runs_health_check() -> None:
    monitor = HealthMonitor()
    check = DummyHealthCheck("test.check", HealthStatus.HEALTHY)

    monitor.register(check)

    results = monitor.run_once()

    assert results == [
        HealthResult(name="test.check", status=HealthStatus.HEALTHY),
    ]


def test_monitor_rejects_duplicate_check_name() -> None:
    monitor = HealthMonitor()
    check = DummyHealthCheck("test.check", HealthStatus.HEALTHY)

    monitor.register(check)

    with pytest.raises(ValueError, match="Health check already registered"):
        monitor.register(check)


def test_monitor_unregisters_health_check() -> None:
    monitor = HealthMonitor()
    check = DummyHealthCheck("test.check", HealthStatus.HEALTHY)

    monitor.register(check)
    monitor.unregister("test.check")

    assert monitor.run_once() == []
    assert monitor.get_status() == HealthStatus.UNKNOWN


def test_monitor_unregister_unknown_check_does_not_fail() -> None:
    monitor = HealthMonitor()

    monitor.unregister("unknown.check")

    assert monitor.get_status() == HealthStatus.UNKNOWN


def test_monitor_status_is_healthy_when_all_checks_are_healthy() -> None:
    monitor = HealthMonitor()
    monitor.register(DummyHealthCheck("check.one", HealthStatus.HEALTHY))
    monitor.register(DummyHealthCheck("check.two", HealthStatus.HEALTHY))

    monitor.run_once()

    assert monitor.get_status() == HealthStatus.HEALTHY


def test_monitor_status_is_degraded_when_one_check_is_degraded() -> None:
    monitor = HealthMonitor()
    monitor.register(DummyHealthCheck("check.one", HealthStatus.HEALTHY))
    monitor.register(DummyHealthCheck("check.two", HealthStatus.DEGRADED))

    monitor.run_once()

    assert monitor.get_status() == HealthStatus.DEGRADED


def test_monitor_status_is_unhealthy_when_one_check_is_unhealthy() -> None:
    monitor = HealthMonitor()
    monitor.register(DummyHealthCheck("check.one", HealthStatus.HEALTHY))
    monitor.register(DummyHealthCheck("check.two", HealthStatus.UNHEALTHY))
    monitor.register(DummyHealthCheck("check.three", HealthStatus.DEGRADED))

    monitor.run_once()

    assert monitor.get_status() == HealthStatus.UNHEALTHY


def test_monitor_status_is_unknown_when_result_contains_unknown_only() -> None:
    monitor = HealthMonitor()
    monitor.register(DummyHealthCheck("check.unknown", HealthStatus.UNKNOWN))

    monitor.run_once()

    assert monitor.get_status() == HealthStatus.UNKNOWN
