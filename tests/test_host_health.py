"""Tests for lightweight host health collection and evaluation."""

from __future__ import annotations

from collections import namedtuple
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess

from plugins.mqtt.host_health import (
    HostHealthMonitor,
    HostHealthObservationMapper,
    HostHealthReporter,
    HostMetrics,
    SystemHostProbe,
    format_uptime,
)


def test_system_host_probe_reads_linux_metrics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    proc_root = tmp_path / "proc"
    thermal_zone = tmp_path / "sys" / "class" / "thermal" / "thermal_zone0"
    proc_root.mkdir()
    thermal_zone.mkdir(parents=True)
    (proc_root / "stat").write_text(
        "cpu 100 0 100 800 0 0 0 0 0 0\n",
        encoding="utf-8",
    )
    (proc_root / "loadavg").write_text("4.00 3.00 2.00 1/1 1\n", encoding="utf-8")
    (proc_root / "meminfo").write_text(
        "MemTotal: 1000 kB\nMemAvailable: 250 kB\nSwapTotal: 100 kB\nSwapFree: 25 kB\n",
        encoding="utf-8",
    )
    (proc_root / "uptime").write_text("3600.50 100.00\n", encoding="utf-8")
    (thermal_zone / "type").write_text("cpu-thermal\n", encoding="utf-8")
    (thermal_zone / "temp").write_text("78000\n", encoding="utf-8")
    monkeypatch.setattr("plugins.mqtt.host_health.os.cpu_count", lambda: 4)
    disk_usage = namedtuple("DiskUsage", "total used free")
    clock_values = iter((100.0, 110.0, 120.0))
    probe = SystemHostProbe(
        proc_root=proc_root,
        sys_root=tmp_path / "sys",
        systemctl_path=tmp_path / "missing-systemctl",
        disk_usage=lambda _path: disk_usage(1000, 900, 100),
        monotonic_clock=lambda: next(clock_values),
    )

    first = probe.collect()
    (proc_root / "stat").write_text(
        "cpu 150 0 150 900 0 0 0 0 0 0\n",
        encoding="utf-8",
    )
    second = probe.collect()

    assert first.cpu_percent is None
    assert second.cpu_percent == 50.0
    assert second.load_1m_per_cpu == 1.0
    assert second.memory_percent == 75.0
    assert second.memory_available_bytes == 250 * 1024
    assert second.swap_percent == 75.0
    assert second.disk_percent == 90.0
    assert second.disk_free_bytes == 100
    assert second.temperature_c == 78.0
    assert second.host_uptime_seconds == 3600
    assert second.agent_uptime_seconds == 20
    assert second.agent_restarts is None
    assert second.failed_systemd_units == ()


def test_system_host_probe_reads_systemd_health(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    systemctl_path = tmp_path / "systemctl"
    systemctl_path.write_text("", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    def runner(command, **_kwargs):
        arguments = tuple(command[1:])
        commands.append(arguments)
        if arguments[0] == "show":
            return CompletedProcess(command, 0, stdout="3\n", stderr="")
        return CompletedProcess(
            command,
            0,
            stdout=(
                "ohana-vision.service loaded failed failed Ohana Vision\n"
                "unrelated.service loaded failed failed Unrelated\n"
            ),
            stderr="",
        )

    probe = SystemHostProbe(
        proc_root=proc_root,
        sys_root=tmp_path / "sys",
        systemctl_path=systemctl_path,
        runner=runner,
    )

    metrics = probe.collect()

    assert metrics.agent_restarts == 3
    assert metrics.failed_systemd_units == ("ohana-vision.service",)
    assert commands == [
        (
            "show",
            "ohana-agent.service",
            "--property=NRestarts",
            "--value",
        ),
        (
            "list-units",
            "--state=failed",
            "--no-legend",
            "--plain",
        ),
    ]


class FakeHostProbe:
    def __init__(self, metrics: HostMetrics) -> None:
        self.metrics = metrics

    def collect(self) -> HostMetrics:
        return self.metrics


def make_metrics(**changes) -> HostMetrics:
    metrics = HostMetrics(
        hostname="infra-01",
        operating_system="Linux",
        kernel="6.12",
        cpu_count=4,
        cpu_percent=10.0,
        load_1m_per_cpu=0.2,
        memory_percent=40.0,
        memory_available_bytes=1_000_000,
        swap_percent=0.0,
        disk_percent=30.0,
        disk_free_bytes=10_000_000,
        temperature_c=50.0,
        host_uptime_seconds=3600,
        agent_uptime_seconds=600,
        agent_restarts=0,
        failed_systemd_units=(),
    )
    return replace(metrics, **changes)


def test_host_health_requires_sustained_resource_pressure() -> None:
    probe = FakeHostProbe(make_metrics(cpu_percent=90.0))
    monitor = HostHealthMonitor(
        probe,
        required_samples=3,
        utc_now=lambda: datetime(2026, 8, 10, 15, 0, tzinfo=UTC),
    )

    assert monitor.collect().state == "healthy"
    assert monitor.collect().state == "healthy"
    snapshot = monitor.collect()

    assert snapshot.state == "degraded"
    assert snapshot.reasons == ("cpu_degraded",)


def test_host_health_reports_immediate_critical_conditions() -> None:
    probe = FakeHostProbe(
        make_metrics(
            disk_percent=96.0,
            agent_restarts=3,
            failed_systemd_units=("ohana-vision.service",),
        )
    )
    monitor = HostHealthMonitor(probe)

    snapshot = monitor.collect()

    assert snapshot.state == "critical"
    assert snapshot.reasons == (
        "disk_critical",
        "agent_restarts_critical",
        "systemd_units_failed",
    )


def test_host_health_recovers_after_pressure_clears() -> None:
    probe = FakeHostProbe(make_metrics(memory_percent=90.0))
    monitor = HostHealthMonitor(probe, required_samples=2)

    monitor.collect()
    assert monitor.collect().state == "degraded"
    probe.metrics = make_metrics(memory_percent=40.0)

    snapshot = monitor.collect()

    assert snapshot.state == "healthy"
    assert snapshot.reasons == ()


def test_host_health_formats_uptimes_for_humans() -> None:
    assert format_uptime(None) == "Inconnu"
    assert format_uptime(45) == "45 s"
    assert format_uptime(121) == "2 min"
    assert format_uptime(761_354) == "8 j 19 h 29 min"

    snapshot = HostHealthMonitor(FakeHostProbe(make_metrics())).collect()

    assert snapshot.to_dict()["host_uptime"] == "1 h 0 min"
    assert snapshot.to_dict()["agent_uptime"] == "10 min"


def test_host_health_maps_to_device_observation_for_vision() -> None:
    snapshot = HostHealthMonitor(
        FakeHostProbe(make_metrics(memory_percent=96.0)),
        required_samples=1,
    ).collect()

    observation = HostHealthObservationMapper().to_observation(snapshot)

    assert observation.node == "infra-01"
    assert observation.service == "ohana-host"
    assert observation.capability == "host.health"
    assert observation.status.value == "unhealthy"
    assert observation.metadata["target_type"] == "device"
    assert observation.metadata["host_health"]["memory_percent"] == 96.0


def test_host_health_reporter_shares_the_same_periodic_snapshot() -> None:
    clock = [10.0]
    monitor = HostHealthMonitor(FakeHostProbe(make_metrics()))
    first_sink = []
    second_sink = []
    reporter = HostHealthReporter(
        monitor,
        sinks=(first_sink.append, second_sink.append),
        interval_seconds=60,
        monotonic_clock=lambda: clock[0],
    )

    reporter.start()
    reporter.tick()
    clock[0] = 70.0
    reporter.tick()

    assert first_sink == second_sink
    assert len(first_sink) == 2
    assert reporter.running is True
    reporter.stop()
    assert reporter.running is False
