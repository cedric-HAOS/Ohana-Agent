"""Which Ohana process grows: resident memory per process, named in the alerts."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_status import ObservationStatus
from ohana_agent.runtime.process_memory import process_rss_bytes
from ohana_agent.tsunade.preventive import TsunadePreventiveMonitor

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=PARIS)
MB = 1_000_000


def test_resident_memory_is_read_from_the_kernel_status(tmp_path: Path) -> None:
    status = tmp_path / "status"
    status.write_text("Name:\tpython3\nVmPeak:\t  300 kB\nVmRSS:\t  148628 kB\n")

    assert process_rss_bytes(status) == 148628 * 1024


@pytest.mark.parametrize("content", ["Name:\tx\n", "VmRSS: lots kB\n", ""])
def test_a_status_without_a_usable_value_gives_nothing(tmp_path, content) -> None:
    status = tmp_path / "status"
    status.write_text(content)

    assert process_rss_bytes(status) is None
    assert process_rss_bytes(tmp_path / "missing") is None


@pytest.fixture
def monitor(tmp_path: Path):
    instance = TsunadePreventiveMonitor(tmp_path / "control.db")
    yield instance
    instance.close()


def _host(at: datetime, **health: object) -> Observation:
    return Observation(
        node="infra-01",
        service="ohana-host",
        capability="host.health",
        status=ObservationStatus.HEALTHY,
        success=True,
        message="Host healthy",
        source="host-health",
        timestamp=at,
        metadata={"host_health": {"disk_percent": 10.0, **health}},
    )


def _history(monitor, agent: list[float], vision: list[float]) -> None:
    for offset, (a, v) in enumerate(
        zip(reversed(agent), reversed(vision), strict=True)
    ):
        at = NOW - timedelta(days=offset)
        monitor.record_host_health(
            _host(
                at,
                agent_rss_bytes=int(a * MB),
                vision={"rss_bytes": int(v * MB), "available": True},
            )
        )


def _memory(summary: dict) -> dict:
    return next(c for c in summary["checks"] if c["id"] == "memory_growth")


def test_a_growing_process_is_named_with_its_daily_rate(monitor) -> None:
    _history(monitor, [100, 120, 141, 160, 181, 200], [90, 90, 91, 90, 90, 91])

    summary = monitor.summary(now=NOW)

    item = next(i for i in summary["watch"] if i["subject"].endswith("agent_rss_bytes"))
    assert item["title"].startswith("INFRA-01 : l'Agent grossit (+")
    assert item["evidence"]["process"] == "l'Agent"
    assert item["evidence"]["slope_mb_per_day"] >= 18
    assert [d["mb"] for d in item["evidence"]["days"]][-1] == 200.0
    assert all("Vision grossit" not in i["title"] for i in summary["watch"])
    summaries = [n["summary"] for n in _memory(summary)["nodes"]]
    assert any("Vision : 91 Mo" in text for text in summaries)


def test_a_stable_process_is_summarised_not_reported(monitor) -> None:
    _history(monitor, [150, 151, 149, 150, 152, 151], [90, 90, 91, 90, 90, 90])

    summary = monitor.summary(now=NOW)

    assert all("grossit" not in i["title"] for i in summary["watch"])
    nodes = _memory(summary)["nodes"]
    assert any(n["summary"].startswith("INFRA-01 · l'Agent : 151 Mo") for n in nodes)


def test_too_few_days_never_make_a_leak(monitor) -> None:
    _history(monitor, [100, 160, 220], [90, 90, 90])

    summary = monitor.summary(now=NOW)

    assert all("grossit" not in i["title"] for i in summary["watch"])


def test_a_jump_without_a_trend_is_not_a_leak(monitor) -> None:
    # A restart after a deployment, then a plateau: not +5 Mo per day.
    _history(monitor, [300, 300, 150, 150, 150, 151], [90, 90, 90, 90, 90, 90])

    assert all("grossit" not in i["title"] for i in monitor.summary(now=NOW)["watch"])


def test_host_memory_alerts_name_the_processes(monitor) -> None:
    for offset in range(14, -1, -1):
        at = NOW - timedelta(days=offset)
        percent = 50.0 if offset > 7 else 78.0
        monitor.record_host_health(
            _host(
                at,
                memory_percent=percent,
                agent_rss_bytes=(150 + (14 - offset) * 2) * MB,
                vision={"rss_bytes": 90 * MB},
            )
        )

    summary = monitor.summary(now=NOW)

    host = next(i for i in summary["watch"] if i["subject"].endswith("memory_percent"))
    assert "Processus : INFRA-01 · l'Agent" in host["detail"]
    assert "Vision" in host["detail"]
