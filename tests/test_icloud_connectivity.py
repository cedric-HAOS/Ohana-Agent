"""Tests for the periodic rclone iCloud session check."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.plugins.backup.config import BackupConfig
from ohana_agent.plugins.backup.icloud_connectivity import (
    ICloudConnectivityProbe,
    ICloudConnectivityReporter,
    classify_failure,
)

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 9, 28, 13, 38, 26, tzinfo=PARIS)


def _config(tmp_path: Path, *, binary: bool = True, conf: bool = True) -> BackupConfig:
    rclone = tmp_path / "rclone"
    config = tmp_path / "rclone.conf"
    if binary:
        rclone.write_text("", encoding="utf-8")
    if conf:
        config.write_text("[icloud]\n", encoding="utf-8")
    return BackupConfig(rclone_binary=str(rclone), rclone_config_path=str(config))


def _runner(code: int, stderr: str = ""):
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] > 0
        return subprocess.CompletedProcess(command, code, "", stderr)

    run.calls = calls
    return run


@pytest.mark.parametrize(
    ("detail", "state"),
    [
        (
            "ERROR : HTTP error 421 (421 Misdirected Request) returned body: "
            '"{\\"reason\\":\\"Invalid global session\\",\\"error\\":2}"',
            "session_expired",
        ),
        ("missing trust token, run rclone config reconnect", "session_expired"),
        # INFRA-01, 28 September 14:00, as the ohana-agent user.
        (
            'CRITICAL: Failed to create file system for "icloud:": '
            "trust token expired, please reauth",
            "session_expired",
        ),
        ("dial tcp: lookup www.icloud.com: no such host", "unreachable"),
        (
            "Failed to create file system: didn't find section in config file",
            "not_configured",
        ),
        ("directory not found", "error"),
    ],
)
def test_rclone_failures_are_classified(detail: str, state: str) -> None:
    assert classify_failure(detail) == state


def test_probe_reports_connected_and_keeps_the_last_success(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = _runner(0)
    probe = ICloudConnectivityProbe(config, runner=runner, now=lambda: NOW)

    connected = probe.check()
    assert connected.state == "connected"
    assert connected.connected is True
    assert connected.checked_at == "2026-09-28T13:38:26+02:00"
    assert connected.last_success_at == connected.checked_at
    command = runner.calls[0]
    assert command[1:3] == ["lsd", "icloud:"]
    assert command[command.index("--config") + 1] == config.rclone_config_path

    # 28 September: the session had expired (HTTP 421).
    probe._runner = _runner(1, 'HTTP error 421 "Invalid global session"')
    expired = probe.check()
    assert expired.state == "session_expired"
    assert expired.connected is False
    assert expired.last_success_at == "2026-09-28T13:38:26+02:00"
    assert "Invalid global session" in (expired.detail or "")


def test_probe_masks_secrets_in_the_detail(tmp_path: Path) -> None:
    probe = ICloudConnectivityProbe(
        _config(tmp_path),
        runner=_runner(1, "auth failed: trust_token=abcdef123 password=hunter2"),
        now=lambda: NOW,
    )
    detail = probe.check().detail or ""
    assert "abcdef123" not in detail
    assert "hunter2" not in detail


@pytest.mark.parametrize(("binary", "conf"), [(False, True), (True, False)])
def test_probe_without_rclone_or_configuration_is_not_configured(
    tmp_path: Path, binary: bool, conf: bool
) -> None:
    runner = _runner(0)
    probe = ICloudConnectivityProbe(
        _config(tmp_path, binary=binary, conf=conf), runner=runner, now=lambda: NOW
    )
    assert probe.check().state == "not_configured"
    assert runner.calls == []


def test_probe_timeout_is_unreachable(tmp_path: Path) -> None:
    def slow(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    probe = ICloudConnectivityProbe(_config(tmp_path), runner=slow, now=lambda: NOW)
    assert probe.check().state == "unreachable"


class _ImmediateThread:
    def __init__(self, *, target, name, daemon) -> None:
        assert daemon is True
        assert name
        self._target = target

    def start(self) -> None:
        self._target()

    def is_alive(self) -> bool:
        return False


def test_reporter_checks_at_start_then_hourly(tmp_path: Path) -> None:
    clock = [0.0]
    received = []
    reporter = ICloudConnectivityReporter(
        ICloudConnectivityProbe(_config(tmp_path), runner=_runner(0), now=lambda: NOW),
        sinks=(received.append,),
        monotonic_clock=lambda: clock[0],
        thread_factory=_ImmediateThread,
    )

    reporter.start()
    assert len(received) == 1
    clock[0] = 3599.0
    reporter.tick()
    assert len(received) == 1
    clock[0] = 3600.0
    reporter.tick()
    assert len(received) == 2

    # A new backup configuration is checked at the next tick.
    reporter.update_config(_config(tmp_path))
    reporter.tick()
    assert len(received) == 3


def test_reporter_never_overlaps_a_slow_check(tmp_path: Path) -> None:
    started = []

    class _StuckThread:
        def __init__(self, **_kwargs) -> None:
            started.append(self)

        def start(self) -> None:
            return None

        def is_alive(self) -> bool:
            return True

    clock = [0.0]
    reporter = ICloudConnectivityReporter(
        ICloudConnectivityProbe(_config(tmp_path), runner=_runner(0), now=lambda: NOW),
        sinks=(),
        monotonic_clock=lambda: clock[0],
        thread_factory=_StuckThread,
    )
    reporter.start()
    clock[0] = 7200.0
    reporter.tick()
    assert len(started) == 1


def test_reporter_survives_a_failing_sink(tmp_path: Path) -> None:
    def broken(_status) -> None:
        raise RuntimeError("MQTT down")

    received = []
    reporter = ICloudConnectivityReporter(
        ICloudConnectivityProbe(_config(tmp_path), runner=_runner(0), now=lambda: NOW),
        sinks=(broken, received.append),
        thread_factory=_ImmediateThread,
    )
    reporter.start()
    assert len(received) == 1
