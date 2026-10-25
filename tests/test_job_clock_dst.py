"""The job clock stays correct in the repeated hour of the autumn clock change."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ohana_agent.jobs.job_types import LOCAL_TIMEZONE
from ohana_agent.jobs.repository import DistributedJobRepository

JOB_ID = "66666666-6666-4666-8666-666666666666"
# 2026-10-25: Europe/Paris goes back from 03:00 CEST to 02:00 CET, so 02:00:02
# happens twice. The second one is 01:00:02 UTC.
SECOND_PASS = datetime(2026, 10, 25, 1, 0, 2, tzinfo=UTC)


def _payload(created_at: datetime) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "job_id": JOB_ID,
        "type": "system.health",
        "created_at": created_at.isoformat(),
        "parameters": {},
        "timeout": 600,
    }


@pytest.fixture
def repository(tmp_path: Path) -> DistributedJobRepository:
    # Production clock: a Paris datetime, which carries fold=1 in this hour.
    instance = DistributedJobRepository(
        tmp_path / "jobs.db",
        clock=lambda: SECOND_PASS.astimezone(LOCAL_TIMEZONE),
    )
    yield instance
    instance.close()


def test_job_created_now_is_accepted_in_the_repeated_hour(
    repository: DistributedJobRepository,
) -> None:
    job = repository.create(_payload(SECOND_PASS))

    assert job.created_at == SECOND_PASS


def test_repository_clock_does_not_drift_by_an_hour_when_shifted(
    repository: DistributedJobRepository,
) -> None:
    from datetime import timedelta

    now = repository.now()

    assert now == SECOND_PASS
    assert now + timedelta(minutes=5) == SECOND_PASS + timedelta(minutes=5)
    assert now.isoformat() == "2026-10-25T02:00:02+01:00"
