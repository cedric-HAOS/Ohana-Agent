"""Shizune must say how the latest daily log check ended, not only when."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from ohana_agent.contracts.administration import DistributedJobStatus
from ohana_agent.jobs.repository import DistributedJobRepository
from ohana_agent.tsunade.companion_overview import log_check_summary, logs_overview


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 5, 4, 45, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _job(clock: Clock, job_id: str) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "job_id": job_id,
        "type": "logs.health_check",
        "created_at": clock.now.isoformat(),
        "parameters": {
            "sources": ["ha-01"],
            "window_started_at": (clock.now - timedelta(hours=24)).isoformat(),
            "window_ended_at": clock.now.isoformat(),
            "max_bytes_per_source": 1048576,
        },
        "timeout": 900,
    }


def test_the_latest_job_can_be_searched_by_status(tmp_path: Path) -> None:
    clock = Clock()
    jobs = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
    older, newer = uuid4(), uuid4()
    jobs.create(_job(clock, str(older)))
    jobs.cancel(str(older))
    clock.now += timedelta(days=1)
    jobs.create(_job(clock, str(newer)))

    assert jobs.latest_for_incident("logs.health_check", None).job_id == newer
    cancelled = jobs.latest_for_incident(
        "logs.health_check", None, DistributedJobStatus.CANCELLED
    )
    assert cancelled.job_id == older
    assert (
        jobs.latest_for_incident(
            "logs.health_check", None, DistributedJobStatus.SUCCEEDED
        )
        is None
    )
    jobs.close()


def test_check_summary_names_the_state_of_the_job() -> None:
    moment = datetime(2026, 11, 6, 5, 2, 35, tzinfo=UTC)

    def job(status: str, **times: datetime | None):
        return SimpleNamespace(
            status=DistributedJobStatus(status),
            created_at=moment - timedelta(minutes=20),
            started_at=times.get("started_at"),
            finished_at=times.get("finished_at"),
        )

    assert log_check_summary(None) == {"state": "none", "at": None}
    assert log_check_summary(job("SUCCEEDED", finished_at=moment))["state"] == (
        "succeeded"
    )
    for status in ("FAILED", "TIMEOUT", "CANCELLED"):
        assert log_check_summary(job(status, finished_at=moment))["state"] == "failed"
    running = log_check_summary(job("RUNNING", started_at=moment))
    assert running["state"] == "running"
    waiting = log_check_summary(job("WAITING_WORKER"))
    assert waiting["state"] == "waiting"
    assert waiting["at"].endswith(("+01:00", "+02:00"))
    failed = log_check_summary(job("FAILED", finished_at=moment))
    assert failed["at"] == "2026-11-06T06:02:35+01:00"


def test_a_failed_check_does_not_report_clean_sources_as_ok() -> None:
    failed = {"state": "failed", "at": "2026-11-06T05:02:35+01:00"}

    block = logs_overview([], set(), {"ha-01": 1}, None, last_check=failed)
    rows = {row["equipment"]: row for row in block["equipments"]}

    assert block["last_check"] == failed
    assert rows["infra-01"]["status"] == "unknown"
    assert rows["infra-01"]["detail"] == "Non vérifié : le dernier contrôle a échoué"
    # Known noise the user accepted remains a statement about the past.
    assert rows["ha-01"]["status"] == "watch"
    assert block["equipments"][0]["status"] == "unknown"

    succeeded = {"state": "succeeded", "at": "2026-11-06T05:02:35+01:00"}
    clean = logs_overview([], set(), {}, None, last_check=succeeded)
    assert {row["status"] for row in clean["equipments"]} == {"ok"}
    assert logs_overview([], set(), {}, None)["last_check"] == {
        "state": "none",
        "at": None,
    }
