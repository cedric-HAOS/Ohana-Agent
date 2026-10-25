"""SD card health: slow writes and a read-only root are reported, not guessed."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_status import ObservationStatus
from ohana_agent.tsunade.preventive import TsunadePreventiveMonitor
from ohana_agent.tsunade.storage_health import StorageSampler

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=PARIS)


def _stat(write_ios: int, write_sectors: int, write_ticks: int) -> str:
    # reads: ios merges sectors ticks | writes: ios merges sectors ticks | ...
    fields = [769708, 41619, 11571482, 917647, write_ios, 0, write_sectors, write_ticks]
    return " ".join(str(value) for value in fields + [0, 0, 0, 0, 0, 0, 0, 0, 0])


class Device:
    """A fake /sys/block/mmcblk0/stat and /proc/mounts."""

    def __init__(self, root: Path) -> None:
        self.sys_block = root / "block"
        (self.sys_block / "mmcblk0").mkdir(parents=True)
        self.mounts = root / "mounts"
        self.set(0, 0, 0)
        self.mount("rw,noatime")

    def set(self, ios: int, sectors: int, ticks: int) -> None:
        (self.sys_block / "mmcblk0" / "stat").write_text(_stat(ios, sectors, ticks))

    def mount(self, options: str) -> None:
        self.mounts.write_text(
            "proc /proc proc rw 0 0\n"
            f"/dev/mmcblk0p2 / ext4 {options} 0 0\n"
            "/dev/mmcblk0p1 /boot/firmware vfat ro 0 0\n"
        )

    def sampler(self) -> StorageSampler:
        return StorageSampler(sys_block=self.sys_block, mounts=self.mounts)


@pytest.fixture
def device(tmp_path: Path) -> Device:
    return Device(tmp_path)


def test_sampler_averages_write_latency_between_two_readings(device) -> None:
    sampler = device.sampler()
    assert sampler.sample().write_latency_ms is None  # first reading

    device.set(ios=100, sectors=2048, ticks=3000)
    sample = sampler.sample()

    assert sample.write_latency_ms == 30.0
    assert sample.written_bytes == 2048 * 512
    assert sample.root_readonly is False


def test_sampler_waits_for_enough_writes_before_averaging(device) -> None:
    sampler = device.sampler()
    sampler.sample()

    device.set(ios=5, sectors=10, ticks=2000)  # 400 ms but only five writes
    assert sampler.sample().write_latency_ms is None

    device.set(ios=30, sectors=20, ticks=2500)  # 25 writes since the baseline
    assert sampler.sample().write_latency_ms == pytest.approx(2500 / 30)


def test_sampler_restarts_after_a_reboot(device) -> None:
    sampler = device.sampler()
    device.set(ios=1000, sectors=9000, ticks=50_000)
    sampler.sample()

    device.set(ios=3, sectors=8, ticks=10)  # counters went back to zero
    sample = sampler.sample()

    assert sample.write_latency_ms is None
    assert sample.written_bytes is None


def test_sampler_detects_a_read_only_root_not_the_boot_partition(device) -> None:
    sampler = device.sampler()
    device.mount("ro,relatime")

    assert sampler.sample().root_readonly is True


def test_sampler_is_inert_without_the_device(tmp_path: Path) -> None:
    sampler = StorageSampler(sys_block=tmp_path / "none", mounts=tmp_path / "mounts")

    assert sampler.available is False
    assert sampler.sample().write_latency_ms is None


def _host(at: datetime) -> Observation:
    return Observation(
        node="infra-01",
        service="ohana-host",
        capability="host.health",
        status=ObservationStatus.HEALTHY,
        success=True,
        message="Host healthy",
        source="host-health",
        timestamp=at,
        metadata={"host_health": {"disk_percent": 10.0}},
    )


def _rule(summary: dict) -> dict:
    return next(c for c in summary["checks"] if c["id"] == "storage_health")


def _history(monitor: TsunadePreventiveMonitor, means: list[float]) -> None:
    """One daily mean per day, the last one being today."""
    for offset, mean in enumerate(reversed(means)):
        day = NOW - timedelta(days=offset)
        for minute in (0, 30):
            monitor.record_metric(
                "infra-01", "sd_write_latency_ms", mean, day + timedelta(minutes=minute)
            )


@pytest.fixture
def monitor(tmp_path: Path, device):
    instance = TsunadePreventiveMonitor(
        tmp_path / "control.db", storage_sampler=device.sampler()
    )
    yield instance
    instance.close()


def test_healthy_card_is_summarised_not_reported(monitor) -> None:
    _history(monitor, [12.0] * 8)

    summary = monitor.summary(now=NOW)

    assert summary["watch"] == []
    check = _rule(summary)
    assert check["state"] == "ok"
    assert check["nodes"][0]["summary"] == "INFRA-01 : écriture SD 12 ms en moyenne"


def test_three_slow_days_in_the_week_are_reported(monitor) -> None:
    _history(monitor, [15.0] * 4 + [130.0, 20.0, 150.0, 140.0])

    item = monitor.summary(now=NOW)["watch"][0]

    assert item["subject"] == "infra-01:sd_latency"
    assert item["urgent"] is False
    assert "3 des 7 derniers jours" in item["detail"]
    assert "284 ms" in item["detail"]


def test_a_very_slow_recent_day_is_urgent(monitor) -> None:
    _history(monitor, [15.0] * 7 + [300.0])

    summary = monitor.summary(now=NOW)

    assert summary["watch"][0]["urgent"] is True
    assert summary["conclusion"].startswith("Intervention à prévoir")


def test_a_card_slowing_down_is_noticed_before_the_absolute_threshold(monitor) -> None:
    _history(monitor, [10.0] * 28 + [60.0] * 7)

    item = monitor.summary(now=NOW)["watch"][0]

    assert item["subject"] == "infra-01:sd_latency_drift"


def test_a_read_only_root_is_urgent(monitor, device) -> None:
    _history(monitor, [12.0] * 3)
    device.mount("ro,relatime")

    monitor.record_host_health(_host(NOW))

    summary = monitor.summary(now=NOW)
    titles = {item["title"] for item in summary["watch"]}
    assert "INFRA-01 : système de fichiers en lecture seule" in titles
    assert any(item["urgent"] for item in summary["watch"])


def test_host_health_feeds_the_daily_aggregates(monitor, device) -> None:
    monitor.record_host_health(_host(NOW - timedelta(minutes=5)))  # baseline
    device.set(ios=200, sectors=4 * 1024 * 1024, ticks=4000)  # 20 ms, 2 GiB
    monitor.record_host_health(_host(NOW))

    check = _rule(monitor.summary(now=NOW))

    assert check["nodes"][0]["summary"] == (
        "INFRA-01 : écriture SD 20 ms en moyenne, 2,1 Go écrits aujourd'hui"
    )


def test_without_a_measure_the_rule_has_nothing_to_judge(monitor) -> None:
    assert _rule(monitor.summary(now=NOW))["state"] == "insufficient_data"


def test_today_is_a_date_in_paris() -> None:
    assert isinstance(NOW.date(), date)
