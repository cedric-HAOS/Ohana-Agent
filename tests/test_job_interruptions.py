"""Phase 6: an interrupted job is resumed a few times, then fails explicitly."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ohana_agent.contracts.administration import DistributedJobStatus
from ohana_agent.jobs.repository import DistributedJobRepository

JOB_ID = "44444444-4444-4444-8444-444444444444"
WORKER = "katsuyu-bubule"
HEALTH_RESULT = {
    "status": "OK",
    "collected_at": "2026-09-29T08:00:00+00:00",
    "platform": "Windows",
    "cpu_percent": 12.5,
    "memory_total_bytes": 1_073_741_824,
    "memory_available_bytes": 536_870_912,
    "disk_total_bytes": 32_000_000_000,
    "disk_free_bytes": 16_000_000_000,
    "temperature_c": None,
    "issues": [],
}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def repository(tmp_path: Path, clock: Clock) -> DistributedJobRepository:
    instance = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
    yield instance
    instance.close()


def _queue(repository: DistributedJobRepository, clock: Clock, kind: str) -> None:
    parameters: dict[str, object] = (
        {
            "incident_id": "55555555-5555-4555-8555-555555555555",
            "question": "Pourquoi ?",
            "evidence": [{"source": "x", "content": "y"}],
        }
        if kind == "ai.inference"
        else {}
    )
    repository.create(
        {
            "protocol_version": 1,
            "job_id": JOB_ID,
            "type": kind,
            "created_at": clock.now.isoformat(),
            "parameters": parameters,
            "timeout": 6 * 3600,
        }
    )


def _claim(repository: DistributedJobRepository, kind: str):
    return repository.claim(
        {"protocol_version": 1, "worker_id": WORKER, "supported_types": [kind]}
    )


def _events(repository: DistributedJobRepository) -> list[str]:
    with repository._lock:  # noqa: SLF001
        rows = repository._connection.execute(  # noqa: SLF001
            "SELECT detail FROM distributed_job_events WHERE job_id = ? "
            "ORDER BY event_id",
            (JOB_ID,),
        ).fetchall()
    return [row["detail"] for row in rows]


def test_an_interrupted_job_is_resumed_and_can_still_succeed(
    repository: DistributedJobRepository, clock: Clock
) -> None:
    _queue(repository, clock, "system.health")
    assert _claim(repository, "system.health").job is not None
    clock.now += timedelta(seconds=61)  # PC lost, heartbeats stopped

    second = _claim(repository, "system.health")

    assert second.job is not None and second.job.attempt == 2
    repository.complete(
        JOB_ID,
        {
            "protocol_version": 1,
            "worker_id": WORKER,
            "attempt": 2,
            "status": "SUCCEEDED",
            "result": HEALTH_RESULT,
        },
    )
    assert repository.get(JOB_ID).status == DistributedJobStatus.SUCCEEDED
    assert "queued for retry (attempt 1/3)" in " ".join(_events(repository))


def test_a_job_interrupted_every_time_fails_explicitly(
    repository: DistributedJobRepository, clock: Clock
) -> None:
    _queue(repository, clock, "system.health")
    for _ in range(3):
        assert _claim(repository, "system.health").job is not None
        clock.now += timedelta(seconds=61)

    failed = repository.get(JOB_ID)

    assert failed.status == DistributedJobStatus.FAILED
    assert failed.attempt == 3
    assert failed.error is not None
    assert failed.error.code == "worker.interrupted"
    assert failed.error.retryable is False
    assert "3 fois" in failed.error.message
    assert failed.finished_at == clock.now
    assert _claim(repository, "system.health").job is None
    assert _events(repository)[-1] == "worker lease expired on attempt 3; giving up"
    # The worker that dropped it keeps the last failure in its own activity.
    repository.register_worker(
        {
            "protocol_version": 1,
            "worker_id": WORKER,
            "capabilities": ["system.health"],
            "platform": "Windows",
            "worker_version": "0.13.0",
        }
    )
    activity = repository.list_workers().workers[0].activity[0]
    assert activity.last_failure_status == DistributedJobStatus.FAILED
    assert "abandon" in (activity.last_failure_message or "")


def test_an_interrupted_ai_job_reaches_tsunade_as_a_failure(
    repository: DistributedJobRepository, clock: Clock
) -> None:
    _queue(repository, clock, "ai.inference")
    for _ in range(3):
        assert _claim(repository, "ai.inference").job is not None
        clock.now += timedelta(seconds=61)

    repository.get(JOB_ID)

    pending = repository.pending_completions(failures_only=True)
    assert [str(job.job_id) for job in pending] == [JOB_ID]
    assert pending[0].error is not None
    assert pending[0].error.code == "worker.interrupted"


def test_the_attempt_limit_is_configurable_and_bounded(
    tmp_path: Path, clock: Clock
) -> None:
    for value in (0, 11):
        with pytest.raises(ValueError, match="max_attempts"):
            DistributedJobRepository(tmp_path / "x.db", max_attempts=value)
    repository = DistributedJobRepository(
        tmp_path / "jobs.db", max_attempts=1, clock=clock
    )
    try:
        _queue(repository, clock, "system.health")
        assert _claim(repository, "system.health").job is not None
        clock.now += timedelta(seconds=61)
        assert repository.get(JOB_ID).status == DistributedJobStatus.FAILED
    finally:
        repository.close()
