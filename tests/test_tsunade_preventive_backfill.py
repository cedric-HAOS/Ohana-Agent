"""Phase 4, lot 3: past days rebuilt by Katsuyu from Home Assistant."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.api.service import AdministrationService
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.jobs.log_sources import LogSourceBroker
from ohana_agent.jobs.repository import DistributedJobRepository
from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_status import ObservationStatus
from ohana_agent.plugins.backup.config import BackupConfig, BackupTarget
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.preventive import TsunadePreventiveMonitor

PARIS = ZoneInfo("Europe/Paris")
WORKER = "katsuyu-test"


def _host(at: datetime, disk: float) -> Observation:
    return Observation(
        node="infra-01",
        service="ohana-host",
        capability="host.health",
        status=ObservationStatus.HEALTHY,
        success=True,
        message="Host healthy",
        source="host-health",
        timestamp=at,
        metadata={"host_health": {"disk_percent": disk}},
    )


def _daily(today: datetime, values: list[float]) -> list[dict]:
    """Past days ending yesterday, as Katsuyu returns them."""
    return [
        {
            "day": (today.date() - timedelta(days=len(values) - offset)).isoformat(),
            "minimum": value - 0.4,
            "maximum": value,
            "last": value - 0.1,
            "hours": 24,
        }
        for offset, value in enumerate(values)
    ]


@pytest.fixture
def konoha(tmp_path: Path):
    now = [datetime.now(PARIS)]
    jobs = DistributedJobRepository(tmp_path / "jobs.db", clock=lambda: now[0])
    incidents = TsunadeIncidentRepository(tmp_path / "control.db")
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    broker = LogSourceBroker(
        BackupConfig(
            targets=(
                BackupTarget(
                    id="ha-01",
                    label="HA-01",
                    url="https://ha-01.ohana.lan:8123/",
                    schedule="0 3 * * *",
                    token="ha-token",
                    timeout=30,
                ),
            )
        ),
        jobs,
    )
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infrastructure.yaml"
        ),
        job_repository=jobs,
        incident_repository=incidents,
        preventive_monitor=monitor,
        log_source_broker=broker,
        agent_node_id="infra-01",
    )
    jobs.register_worker(
        {
            "worker_id": WORKER,
            "platform": "Windows",
            "worker_version": "test",
            "capabilities": ["trends.history_backfill"],
        }
    )
    yield service, jobs, monitor, now
    monitor.close()
    incidents.close()
    jobs.close()


def _claim(service):
    return service.next_worker_job(
        {"worker_id": WORKER, "supported_types": ["trends.history_backfill"]}
    ).job


def test_rebuilt_days_never_replace_what_the_agent_measured(tmp_path: Path) -> None:
    today = datetime(2026, 9, 28, 12, 0, tzinfo=PARIS)
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    monitor.record_host_health(_host(today - timedelta(days=1), 99.0))
    monitor.record_host_health(_host(today, 74.0))
    monitor.flush()
    assert monitor.missing_days("infra-01", "disk_percent", now=today) == [
        (today.date() - timedelta(days=offset)).isoformat()
        for offset in (6, 5, 4, 3, 2)
    ]

    inserted = monitor.record_backfill(
        "infra-01",
        "disk_percent",
        _daily(today, [69.0, 70.1, 71.0, 72.2, 73.1, 1.0])
        + [
            {
                "day": today.date().isoformat(),
                "minimum": 1,
                "maximum": 1,
                "last": 1,
                "hours": 12,
            }
        ],
        source="home_assistant",
        now=today,
    )

    # Yesterday (measured live) and today (in progress) are kept.
    assert inserted == 5
    assert monitor.missing_days("infra-01", "disk_percent", now=today) == []
    check = next(
        c for c in monitor.summary(now=today)["checks"] if c["id"] == "disk_growth"
    )
    [node] = check["nodes"]
    assert node["rebuilt_days"] == 5
    assert node["days"] == 7
    assert node["latest_percent"] == 74.0


def test_automatic_backfill_asks_katsuyu_once_for_missing_days(konoha) -> None:
    service, jobs, _monitor, now = konoha

    job = service.request_preventive_backfill(now=now[0], automatic=True)

    assert job.type == "trends.history_backfill"
    midnight = now[0].replace(hour=0, minute=0, second=0, microsecond=0)
    assert job.parameters == {
        "source": "ha-01",
        "node_id": "infra-01",
        "metric": "disk_percent",
        "unique_id": "ohana_host_disk_usage",
        "window_started_at": (midnight - timedelta(days=30)).isoformat(),
        "window_ended_at": midnight.isoformat(),
    }
    assert service.request_preventive_backfill(now=now[0], automatic=True) is None
    assert "preventive.backfill" in service.capabilities().operations
    state = service.read_preventive_summary()["backfill"]
    assert state["job"]["status"] == job.status.value


def test_the_katsuyu_result_fills_the_rule_window(konoha) -> None:
    service, jobs, monitor, now = konoha
    created = service.request_preventive_backfill(now=now[0])
    claim = _claim(service)
    assert claim.job_id == created.job_id

    descriptor = service.read_history_source(
        str(claim.job_id), WORKER, claim.attempt, "ha-01"
    )
    assert descriptor["base_url"] == "https://ha-01.ohana.lan:8123"
    assert descriptor["access_token"] == "ha-token"
    with pytest.raises(ValueError):
        service.read_history_source(
            str(claim.job_id), WORKER, claim.attempt, "zwave-01"
        )

    service.complete_job(
        str(claim.job_id),
        {
            "worker_id": WORKER,
            "attempt": claim.attempt,
            "status": "SUCCEEDED",
            "result": {
                "status": "OK",
                "collected_at": now[0].isoformat(),
                "source": "ha-01",
                "node_id": "infra-01",
                "metric": "disk_percent",
                "entity_id": "sensor.ohana_host_disk_usage",
                "rows_read": 720,
                "days": _daily(now[0], [70.0, 71.2, 72.1, 73.4, 74.5, 75.6]),
            },
        },
    )

    summary = service.read_preventive_summary()
    assert [item["rule"] for item in summary["watch"]] == ["disk_growth"]
    assert summary["backfill"]["job"]["days"] == 6
    assert summary["backfill"]["job"]["entity_id"] == "sensor.ohana_host_disk_usage"
    assert monitor.missing_days("infra-01", "disk_percent") == []
    # The Agent measures today live; tomorrow nothing is missing any more,
    # so no new automatic request once the 24 h guard has passed.
    monitor.record_host_health(_host(now[0], 75.9))
    monitor.flush()
    now[0] += timedelta(hours=25)
    assert service.request_preventive_backfill(now=now[0], automatic=True) is None


def test_without_katsuyu_the_simple_checks_still_answer(tmp_path: Path) -> None:
    incidents = TsunadeIncidentRepository(tmp_path / "control.db")
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infrastructure.yaml"
        ),
        incident_repository=incidents,
        preventive_monitor=monitor,
    )
    try:
        assert service.request_preventive_backfill(automatic=True) is None
        with pytest.raises(LookupError):
            service.request_preventive_backfill()
        summary = service.read_preventive_summary()
        assert summary["backfill"] is None
        assert summary["conclusion"] == "Aucune intervention nécessaire."
        assert "preventive.backfill" not in service.capabilities().operations
    finally:
        monitor.close()
        incidents.close()
