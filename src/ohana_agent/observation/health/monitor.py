"""Health monitoring primitives for Ohana-Agent."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class HealthStatus(StrEnum):
    """Represents the health status of a component."""

    HEALTHY = "healthy"
    SUSPENDED = "suspended"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HealthResult:
    """Represents the result of a health check."""

    name: str
    status: HealthStatus
    message: str | None = None
    details: dict[str, Any] | None = None


class HealthCheck(Protocol):
    """Protocol implemented by health checks."""

    name: str

    def run(self) -> HealthResult:
        """Run the health check."""
        ...


class HealthMonitor:
    """Central health monitor for registered checks."""

    def __init__(self) -> None:
        self._checks: dict[str, HealthCheck] = {}
        self._last_results: list[HealthResult] = []

    def register(self, check: HealthCheck) -> None:
        """Register a health check."""
        if check.name in self._checks:
            raise ValueError(f"Health check already registered: {check.name}")

        self._checks[check.name] = check

    def unregister(self, name: str) -> None:
        """Unregister a health check."""
        self._checks.pop(name, None)

    def run_once(self) -> list[HealthResult]:
        """Run all registered health checks once."""
        results = [check.run() for check in self._checks.values()]
        self._last_results = results
        return results

    def get_status(self) -> HealthStatus:
        """Return the aggregated health status."""
        if not self._last_results:
            return HealthStatus.UNKNOWN

        statuses = [result.status for result in self._last_results]

        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY

        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED

        active_statuses = [
            status for status in statuses if status is not HealthStatus.SUSPENDED
        ]

        if not active_statuses and statuses:
            return HealthStatus.SUSPENDED

        if all(status == HealthStatus.HEALTHY for status in active_statuses):
            return HealthStatus.HEALTHY

        return HealthStatus.UNKNOWN
