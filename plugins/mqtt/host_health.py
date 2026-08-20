"""Collect and evaluate lightweight host health metrics."""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import socket
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from observer import Observation, ObservationStatus

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HostMetrics:
    """Raw host metrics collected without elevated privileges."""

    hostname: str
    operating_system: str
    kernel: str
    cpu_count: int
    cpu_percent: float | None
    load_1m_per_cpu: float | None
    memory_percent: float | None
    memory_total_bytes: int | None
    memory_available_bytes: int | None
    swap_percent: float | None
    swap_total_bytes: int | None
    swap_used_bytes: int | None
    disk_percent: float | None
    disk_free_bytes: int | None
    temperature_c: float | None
    host_uptime_seconds: int | None
    agent_uptime_seconds: int
    agent_restarts: int | None
    failed_systemd_units: tuple[str, ...]
    inactive_systemd_units: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HostHealthSnapshot:
    """Home Assistant payload for the Agent host."""

    state: str
    reasons: tuple[str, ...]
    updated_at: str
    hostname: str
    operating_system: str
    kernel: str
    cpu_count: int
    cpu_percent: float | None
    load_1m_per_cpu: float | None
    memory_percent: float | None
    memory_total_bytes: int | None
    memory_available_bytes: int | None
    swap_percent: float | None
    swap_total_bytes: int | None
    swap_used_bytes: int | None
    disk_percent: float | None
    disk_free_bytes: int | None
    temperature_c: float | None
    host_uptime_seconds: int | None
    agent_uptime_seconds: int
    agent_restarts: int | None
    failed_systemd_units: tuple[str, ...]
    inactive_systemd_units: tuple[str, ...]

    def to_json(self) -> str:
        """Serialize the snapshot using stable compact JSON."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the complete transport representation."""
        payload = asdict(self)
        payload["host_uptime"] = format_uptime(self.host_uptime_seconds)
        payload["agent_uptime"] = format_uptime(self.agent_uptime_seconds)
        return payload


def format_uptime(seconds: int | None) -> str:
    """Format an uptime as a compact French human-readable duration."""
    if seconds is None:
        return "Inconnu"

    remaining = max(int(seconds), 0)
    days, remaining = divmod(remaining, 86_400)
    hours, remaining = divmod(remaining, 3_600)
    minutes, seconds = divmod(remaining, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days} j")
    if hours or days:
        parts.append(f"{hours} h")
    if minutes or hours or days:
        parts.append(f"{minutes} min")
    if not parts:
        parts.append(f"{seconds} s")
    return " ".join(parts)


class SystemHostProbe:
    """Read Linux host metrics using procfs, sysfs and systemd."""

    def __init__(
        self,
        *,
        proc_root: Path = Path("/proc"),
        sys_root: Path = Path("/sys"),
        systemctl_path: Path = Path("/usr/bin/systemctl"),
        disk_usage: Callable[[str], Any] = shutil.disk_usage,
        runner: Callable[..., Any] = subprocess.run,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        self._proc_root = proc_root
        self._sys_root = sys_root
        self._systemctl_path = systemctl_path
        self._disk_usage = disk_usage
        self._runner = runner
        self._monotonic_clock = monotonic_clock
        self._agent_started_at = monotonic_clock()
        self._previous_cpu_times: tuple[int, int] | None = None

    def collect(self) -> HostMetrics:
        """Collect one host sample, leaving unavailable metrics unset."""
        cpu_count = max(os.cpu_count() or 1, 1)
        memory = self._memory_metrics()
        disk = self._disk_metrics()

        return HostMetrics(
            hostname=socket.gethostname(),
            operating_system=platform.system(),
            kernel=platform.release(),
            cpu_count=cpu_count,
            cpu_percent=self._cpu_percent(),
            load_1m_per_cpu=self._load_1m_per_cpu(cpu_count),
            memory_percent=memory[0],
            memory_total_bytes=memory[1],
            memory_available_bytes=memory[2],
            swap_percent=memory[3],
            swap_total_bytes=memory[4],
            swap_used_bytes=memory[5],
            disk_percent=disk[0],
            disk_free_bytes=disk[1],
            temperature_c=self._temperature_c(),
            host_uptime_seconds=self._host_uptime_seconds(),
            agent_uptime_seconds=max(
                int(self._monotonic_clock() - self._agent_started_at),
                0,
            ),
            agent_restarts=self._agent_restarts(),
            failed_systemd_units=self._failed_systemd_units(),
            inactive_systemd_units=self._inactive_systemd_units(),
        )

    def _cpu_percent(self) -> float | None:
        current = self._cpu_times()
        previous = self._previous_cpu_times
        self._previous_cpu_times = current
        if current is None or previous is None:
            return None

        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]
        if total_delta <= 0:
            return None
        return round(
            max(min((total_delta - idle_delta) / total_delta * 100, 100), 0), 1
        )

    def _cpu_times(self) -> tuple[int, int] | None:
        try:
            fields = (
                (self._proc_root / "stat")
                .read_text(encoding="utf-8")
                .splitlines()[0]
                .split()
            )
            if not fields or fields[0] != "cpu":
                return None
            values = [int(value) for value in fields[1:]]
        except (OSError, ValueError, IndexError):
            return None

        total = sum(values)
        idle = sum(values[3:5])
        return total, idle

    def _load_1m_per_cpu(self, cpu_count: int) -> float | None:
        try:
            load = float(
                (self._proc_root / "loadavg").read_text(encoding="utf-8").split()[0]
            )
        except (OSError, ValueError, IndexError):
            return None
        return round(load / cpu_count, 2)

    def _memory_metrics(
        self,
    ) -> tuple[
        float | None,
        int | None,
        int | None,
        float | None,
        int | None,
        int | None,
    ]:
        try:
            lines = (self._proc_root / "meminfo").read_text(encoding="utf-8")
        except OSError:
            return None, None, None, None, None, None

        values: dict[str, int] = {}
        for line in lines.splitlines():
            key, separator, raw_value = line.partition(":")
            if not separator:
                continue
            try:
                values[key] = int(raw_value.strip().split()[0]) * 1024
            except (ValueError, IndexError):
                continue

        total = values.get("MemTotal")
        available = values.get("MemAvailable")
        memory_percent = (
            round((total - available) / total * 100, 1)
            if total and available is not None
            else None
        )
        swap_total = values.get("SwapTotal")
        swap_free = values.get("SwapFree")
        swap_percent = (
            round((swap_total - swap_free) / swap_total * 100, 1)
            if swap_total and swap_free is not None
            else 0.0
            if swap_total == 0
            else None
        )
        swap_used = (
            swap_total - swap_free
            if swap_total is not None and swap_free is not None
            else None
        )
        return memory_percent, total, available, swap_percent, swap_total, swap_used

    def _disk_metrics(self) -> tuple[float | None, int | None]:
        try:
            usage = self._disk_usage("/")
        except OSError:
            return None, None
        percent = round(usage.used / usage.total * 100, 1) if usage.total else None
        return percent, usage.free

    def _temperature_c(self) -> float | None:
        thermal_root = self._sys_root / "class" / "thermal"
        try:
            zones = sorted(thermal_root.glob("thermal_zone*"))
        except OSError:
            return None

        for zone in zones:
            try:
                temperature = float((zone / "temp").read_text(encoding="utf-8"))
                if temperature > 1000:
                    temperature /= 1000
                temperature = round(temperature, 1)
                zone_type = (zone / "type").read_text(encoding="utf-8").strip().lower()
            except (OSError, ValueError):
                continue
            if any(name in zone_type for name in ("cpu", "soc", "core")):
                return temperature
        return None

    def _host_uptime_seconds(self) -> int | None:
        try:
            return int(
                float(
                    (self._proc_root / "uptime").read_text(encoding="utf-8").split()[0]
                )
            )
        except (OSError, ValueError, IndexError):
            return None

    def _agent_restarts(self) -> int | None:
        result = self._run_systemctl(
            "show",
            "ohana-agent.service",
            "--property=NRestarts",
            "--value",
        )
        if result is None or result.returncode != 0:
            return None
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None

    def _failed_systemd_units(self) -> tuple[str, ...]:
        result = self._run_systemctl(
            "list-units",
            "--state=failed",
            "--no-legend",
            "--plain",
        )
        if result is None or result.returncode != 0:
            return ()
        return tuple(
            sorted(
                {
                    fields[0]
                    for line in result.stdout.splitlines()
                    if (fields := line.split()) and fields[0].startswith("ohana-")
                }
            )
        )

    def _inactive_systemd_units(self) -> tuple[str, ...]:
        inactive: list[str] = []
        for unit in ("ohana-vision.service",):
            result = self._run_systemctl("is-active", unit)
            if result is not None and result.returncode != 0:
                inactive.append(unit)
        return tuple(inactive)

    def _run_systemctl(self, *arguments: str) -> Any | None:
        if not self._systemctl_path.is_file():
            return None
        try:
            return self._runner(
                [str(self._systemctl_path), *arguments],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None


class HostHealthMonitor:
    """Evaluate host samples using stable operational thresholds."""

    def __init__(
        self,
        probe: SystemHostProbe,
        *,
        required_samples: int = 3,
        utc_now: Callable[[], datetime] | None = None,
    ) -> None:
        self._probe = probe
        self._required_samples = max(required_samples, 1)
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._streaks: dict[str, int] = {}

    def collect(self) -> HostHealthSnapshot:
        """Collect and evaluate one host health snapshot."""
        metrics = self._probe.collect()
        conditions = self._conditions(metrics)
        active: list[tuple[str, str]] = []
        observed = {key for key, _severity, _reason, _immediate in conditions}

        for key in set(self._streaks) - observed:
            self._streaks[key] = 0

        for key, severity, reason, immediate in conditions:
            self._streaks[key] = self._streaks.get(key, 0) + 1
            if immediate or self._streaks[key] >= self._required_samples:
                active.append((severity, reason))

        state = "healthy"
        if any(severity == "critical" for severity, _reason in active):
            state = "critical"
        elif active:
            state = "degraded"

        return HostHealthSnapshot(
            state=state,
            reasons=tuple(reason for _severity, reason in active),
            updated_at=self._utc_now().isoformat(),
            **asdict(metrics),
        )

    @staticmethod
    def _conditions(
        metrics: HostMetrics,
    ) -> list[tuple[str, str, str, bool]]:
        conditions: list[tuple[str, str, str, bool]] = []

        def threshold(
            key: str,
            value: float | None,
            degraded: float,
            critical: float,
            *,
            immediate: bool = False,
        ) -> None:
            if value is None or value < degraded:
                return
            severity = "critical" if value >= critical else "degraded"
            conditions.append((key, severity, f"{key}_{severity}", immediate))

        threshold("cpu", metrics.cpu_percent, 85, 95)
        threshold("load", metrics.load_1m_per_cpu, 1, 2)
        threshold("memory", metrics.memory_percent, 85, 95)
        threshold("swap", metrics.swap_percent, 50, 80)
        threshold("disk", metrics.disk_percent, 85, 95, immediate=True)
        threshold("temperature", metrics.temperature_c, 75, 82)

        if metrics.agent_restarts is not None and metrics.agent_restarts >= 1:
            severity = "critical" if metrics.agent_restarts >= 3 else "degraded"
            conditions.append(
                ("agent_restarts", severity, f"agent_restarts_{severity}", True)
            )
        if metrics.failed_systemd_units:
            conditions.append(
                ("systemd_units", "degraded", "systemd_units_failed", True)
            )
        if metrics.inactive_systemd_units:
            conditions.append(
                ("systemd_inactive", "degraded", "systemd_units_inactive", True)
            )

        return conditions


class HostHealthObservationMapper:
    """Map one host snapshot to the standard Agent-to-Vision contract."""

    _STATUS_MAPPING = {
        "healthy": ObservationStatus.HEALTHY,
        "degraded": ObservationStatus.DEGRADED,
        "critical": ObservationStatus.UNHEALTHY,
    }

    def to_observation(self, snapshot: HostHealthSnapshot) -> Observation:
        """Build a device-scoped observation that does not alter service health."""
        status = self._STATUS_MAPPING.get(snapshot.state, ObservationStatus.UNKNOWN)
        return Observation(
            node=snapshot.hostname,
            service="ohana-host",
            capability="host.health",
            status=status,
            success=status is ObservationStatus.HEALTHY,
            message=(
                ", ".join(snapshot.reasons) if snapshot.reasons else "Host healthy"
            ),
            source="host-health",
            timestamp=datetime.fromisoformat(snapshot.updated_at),
            metadata={
                "target_type": "device",
                "device_id": snapshot.hostname,
                "host_health": snapshot.to_dict(),
            },
        )


class HostHealthReporter:
    """Collect one snapshot and deliver it to Home Assistant and Vision."""

    def __init__(
        self,
        monitor: HostHealthMonitor,
        *,
        sinks: tuple[Callable[[HostHealthSnapshot], None], ...],
        interval_seconds: float = 60.0,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero.")
        self._monitor = monitor
        self._sinks = sinks
        self._interval_seconds = interval_seconds
        self._monotonic_clock = monotonic_clock
        self._started = False
        self._next_collection_at: float | None = None

    @property
    def running(self) -> bool:
        """Return whether periodic collection is active."""
        return self._started

    def start(self) -> None:
        """Publish an initial snapshot and schedule the next collection."""
        if self._started:
            return
        self._started = True
        self._publish()
        self._next_collection_at = self._monotonic_clock() + self._interval_seconds

    def tick(self) -> None:
        """Publish a snapshot when the collection interval is due."""
        if not self._started:
            return
        now = self._monotonic_clock()
        if self._next_collection_at is not None and now < self._next_collection_at:
            return
        self._publish()
        self._next_collection_at = now + self._interval_seconds

    def stop(self) -> None:
        """Stop periodic collection."""
        self._started = False
        self._next_collection_at = None

    def _publish(self) -> None:
        snapshot = self._monitor.collect()
        for sink in self._sinks:
            try:
                sink(snapshot)
            except Exception as error:
                LOGGER.warning("Unable to publish host health: %s", error)
