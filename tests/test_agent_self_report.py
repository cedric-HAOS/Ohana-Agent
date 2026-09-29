"""Phase 5 hardening: the Agent's detailed report for the Ohana view."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ohana_agent.api.service import AdministrationService
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.jobs.repository import DistributedJobRepository
from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_status import ObservationStatus
from ohana_agent.plugins.mqtt.host_health import database_bytes
from ohana_agent.runtime.release_check import (
    KATSUYU_LATEST_URL,
    LATEST_RELEASE_URL,
    ReleaseCheck,
    compare_versions,
    fetch_recommended,
)
from ohana_agent.runtime.self_report import AgentSelfReport
from ohana_agent.runtime.vision_probe import VisionVitalsProbe
from ohana_agent.scheduler import IntervalTrigger, Scheduler, Task
from ohana_agent.scheduler.clock import FakeClock
from ohana_agent.tsunade.preventive import TsunadePreventiveMonitor

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=PARIS)

CATALOG = """
schema_version: 1
default_platform_version: "1.0.134"
releases:
  - platform_version: "1.0.134"
    release_tag: v1.0.134
    agent_version: "1.41.0"
    vision_version: "1.32.0"
    shizune_version: "0.4.0"
    status: recommended
  - platform_version: "1.0.133"
    release_tag: v1.0.133
    agent_version: "1.40.0"
    vision_version: "1.31.0"
    status: supported
"""


def fake_github(url: str, timeout: float) -> bytes:
    del timeout
    if url == LATEST_RELEASE_URL:
        return json.dumps(
            {
                "tag_name": "v1.0.134",
                "assets": [
                    {"name": "release-catalog.yaml", "browser_download_url": "cat"}
                ],
            }
        ).encode()
    if url == KATSUYU_LATEST_URL:
        return b'{"tag_name": "v0.12.0"}'
    assert url == "cat"
    return CATALOG.encode()


def test_recommended_release_comes_from_the_latest_catalogue() -> None:
    assert fetch_recommended(fake_github) == {
        "katsuyu_version": "0.12.0",
        "platform_version": "1.0.134",
        "agent_version": "1.41.0",
        "vision_version": "1.32.0",
        "shizune_version": "0.4.0",
    }


def test_versions_compare_numerically() -> None:
    assert compare_versions("1.40.0", "1.41.0") == "outdated"
    assert compare_versions("1.41.0", "1.41.0") == "current"
    assert compare_versions("1.10.0", "1.9.0") == "ahead"
    assert compare_versions(None, "1.0.0") == "unknown"
    assert compare_versions("dev", "1.0.0") == "unknown"


def test_release_check_keeps_the_last_answer_when_github_fails() -> None:
    answers = [lambda: fetch_recommended(fake_github)]

    def fetch():
        return answers.pop(0)()

    check = ReleaseCheck(fetch=fetch)
    check.check_now()

    def unreachable():
        raise OSError("no route to host")

    answers.append(unreachable)
    state = check.check_now()

    assert state["recommended"]["agent_version"] == "1.41.0"
    assert state["error"] == "OSError: no route to host"


def test_job_vitals_count_queues_and_retention(tmp_path: Path) -> None:
    repository = DistributedJobRepository(
        tmp_path / "jobs.db", clock=lambda: NOW, retention_days=30
    )
    vitals = repository.vitals()
    assert vitals["active"] == 0
    assert vitals["retention_days"] == 30
    assert vitals["oldest_finished_at"] is None
    assert vitals["retention_overdue"] is False
    repository.close()


def test_report_flags_a_late_scheduler_and_a_vision_backlog(tmp_path: Path) -> None:
    (tmp_path / "distributed-jobs.db").write_bytes(b"x" * 1000)
    (tmp_path / "distributed-jobs.db-wal").write_bytes(b"x" * 24)
    (tmp_path / "notes.txt").write_text("ignored")
    scheduler = Scheduler(clock=FakeClock(NOW))
    for index in range(4):
        scheduler.add_task(
            Task(
                command="noop",
                trigger=IntervalTrigger(timedelta(minutes=1), start_at=NOW),
                name=f"task-{index}",
            )
        )
    scheduler.start()
    check = ReleaseCheck(fetch=lambda: fetch_recommended(fake_github))
    check.check_now()
    report = AgentSelfReport(
        scheduler=scheduler,
        data_directory=tmp_path,
        agent_version="1.40.0",
        outbox_pending=lambda: 812,
        vision_status=lambda: {"available": True, "version": "1.32.0"},
        release_check=check,
        clock=lambda: NOW,
    ).snapshot()

    assert report["scheduler"]["state"] == "late"
    assert report["scheduler"]["overdue_tasks"] == 4
    assert report["queues"]["vision_outbox"] == {"pending": 812, "state": "backlog"}
    assert report["storage"]["total_bytes"] == 1024
    assert [item["name"] for item in report["storage"]["files"]] == [
        "distributed-jobs.db",
        "distributed-jobs.db-wal",
    ]
    assert database_bytes(tmp_path) == 1024
    assert report["versions"]["agent"] == {
        "installed": "1.40.0",
        "recommended": "1.41.0",
        "state": "outdated",
    }
    assert report["versions"]["vision"]["state"] == "current"
    assert report["versions"]["katsuyu_latest"] == "0.12.0"


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
        metadata={"host_health": health},
    )


def test_database_growth_is_the_daily_maximum_over_the_window(tmp_path: Path) -> None:
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    for offset, (agent, vision) in enumerate(
        [(10_000_000, 200_000_000), (12_000_000, 210_000_000), (16_000_000, None)]
    ):
        monitor.record_host_health(
            _host(
                NOW - timedelta(days=2 - offset),
                memory_percent=50.0,
                ohana_data_bytes=agent,
                vision={"available": True, "database_bytes": vision},
            )
        )
    growth = monitor.storage_growth(now=NOW)

    assert growth["agent"]["bytes_per_day"] == 3_000_000
    assert growth["agent"]["latest_bytes"] == 16_000_000
    assert growth["vision"]["days"] == 2
    monitor.close()


def test_agent_serves_its_vitals_detail(tmp_path: Path) -> None:
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infrastructure.yaml"
        ),
        self_report=lambda: {"schema_version": 1},
    )

    assert "agent.vitals.read" in service.capabilities().operations
    assert service.read_agent_vitals() == {"schema_version": 1}


def test_vision_probe_keeps_version_and_database_size() -> None:
    probe = VisionVitalsProbe(
        "http://vision.test/api/runtime/vitals",
        fetch=lambda _url, _timeout: {
            "state": "running",
            "version": "1.32.0",
            "storage": {"database_bytes": 123},
        },
    )
    measure = probe.check_now()

    assert measure["version"] == "1.32.0"
    assert measure["database_bytes"] == 123
