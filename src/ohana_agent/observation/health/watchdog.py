"""Watchdog support for heartbeat-based health monitoring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ohana_agent.observation.health.monitor import HealthResult, HealthStatus


@dataclass
class Watchdog:
    """Monitors heartbeat freshness for a source."""

    source: str
    timeout_seconds: int
    degraded_after_seconds: int | None = None
    last_seen: datetime | None = None

    def heartbeat(self, timestamp: datetime) -> None:
        """Record a heartbeat timestamp."""
        self.last_seen = timestamp

    def check(self, now: datetime) -> HealthResult:
        """Return the current health result for this watchdog."""
        if self.last_seen is None:
            return HealthResult(
                name=self.source,
                status=HealthStatus.UNKNOWN,
                message="No heartbeat received yet.",
            )

        elapsed = (now - self.last_seen).total_seconds()

        if elapsed > self.timeout_seconds:
            return HealthResult(
                name=self.source,
                status=HealthStatus.UNHEALTHY,
                message="Heartbeat timeout exceeded.",
                details={"elapsed_seconds": elapsed},
            )

        if (
            self.degraded_after_seconds is not None
            and elapsed > self.degraded_after_seconds
        ):
            return HealthResult(
                name=self.source,
                status=HealthStatus.DEGRADED,
                message="Heartbeat degraded threshold exceeded.",
                details={"elapsed_seconds": elapsed},
            )

        return HealthResult(
            name=self.source,
            status=HealthStatus.HEALTHY,
            message="Heartbeat is fresh.",
            details={"elapsed_seconds": elapsed},
        )


class WatchdogRegistry:
    """Registry for source watchdogs."""

    def __init__(self, now: Callable[[], datetime]) -> None:
        self._now = now
        self._watchdogs: dict[str, Watchdog] = {}

    def register(
        self,
        source: str,
        timeout_seconds: int,
        degraded_after_seconds: int | None = None,
    ) -> None:
        """Register a watchdog."""
        if source in self._watchdogs:
            raise ValueError(f"Watchdog already registered: {source}")

        self._watchdogs[source] = Watchdog(
            source=source,
            timeout_seconds=timeout_seconds,
            degraded_after_seconds=degraded_after_seconds,
        )

    def heartbeat(self, source: str) -> None:
        """Record a heartbeat for a registered source."""
        watchdog = self._watchdogs.get(source)

        if watchdog is None:
            return

        watchdog.heartbeat(self._now())

    def check_all(self) -> list[HealthResult]:
        """Check all registered watchdogs."""
        now = self._now()
        return [watchdog.check(now) for watchdog in self._watchdogs.values()]
