"""Phase 6: why Ohana woke Katsuyu, what it ran and how the cycle ended."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ohana_agent.api.http import AdministrationHTTPServer
from ohana_agent.api.service import AdministrationService
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.jobs.repository import DistributedJobRepository

WORKER = "katsuyu-bubule"
REGISTRATION: dict[str, object] = {
    "protocol_version": 1,
    "worker_id": WORKER,
    "capabilities": ["system.health"],
    "platform": "Windows 11",
    "worker_version": "0.13.0",
    "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
}
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


def _queue(repository: DistributedJobRepository, clock: Clock, job_id: str) -> None:
    repository.create(
        {
            "protocol_version": 1,
            "job_id": job_id,
            "type": "system.health",
            "created_at": clock.now.isoformat(),
            "parameters": {},
            "timeout": 3600,
        }
    )


def _claim_and_complete(
    repository: DistributedJobRepository, clock: Clock, *, succeed: bool = True
) -> None:
    claimed = repository.claim(
        {
            "protocol_version": 1,
            "worker_id": WORKER,
            "supported_types": ["system.health"],
        }
    )
    assert claimed.job is not None
    clock.now += timedelta(seconds=20)
    repository.complete(
        str(claimed.job.job_id),
        {
            "protocol_version": 1,
            "worker_id": WORKER,
            "attempt": claimed.job.attempt,
            "status": "SUCCEEDED" if succeed else "FAILED",
            "result": HEALTH_RESULT if succeed else None,
            "error": (
                None
                if succeed
                else {"code": "handler.failed", "message": "x", "retryable": False}
            ),
        },
    )


def _events(repository: DistributedJobRepository) -> list:
    return list(reversed(repository.list_workers().workers[0].power_events))


def _settle(repository: DistributedJobRepository) -> object:
    return repository.claim(
        {
            "protocol_version": 1,
            "worker_id": WORKER,
            "supported_types": ["system.health"],
        },
        settle=True,
    )


def test_a_full_cycle_keeps_reason_delay_work_and_shutdown(
    repository: DistributedJobRepository, clock: Clock
) -> None:
    repository.register_worker(REGISTRATION)
    clock.now += timedelta(hours=1)  # heartbeat lapsed: Katsuyu is off
    _queue(repository, clock, "10000000-0000-4000-8000-000000000001")
    _queue(repository, clock, "10000000-0000-4000-8000-000000000002")

    repository.mark_worker_waking(WORKER, timeout_seconds=180, trigger="queued_jobs")
    clock.now += timedelta(seconds=64)
    repository.register_worker(REGISTRATION)
    _claim_and_complete(repository, clock)
    _claim_and_complete(repository, clock, succeed=False)
    result = _settle(repository)
    assert result.shutdown_requested is True
    repository.report_worker_power(
        {
            "protocol_version": 1,
            "worker_id": WORKER,
            "outcome": "shutdown_started",
        }
    )

    kinds = [event.kind.value for event in _events(repository)]
    assert kinds == [
        "wake_sent",
        "worker_online",
        "shutdown_granted",
        "shutdown_started",
    ]
    wake, online, granted, started = _events(repository)
    assert wake.detail == {
        "trigger": "queued_jobs",
        "pending_jobs": {"system.health": 2},
        "timeout_seconds": 180,
    }
    assert online.detail == {"after_seconds": 64}
    assert granted.detail == {"executed": {"system.health": 2}, "failed": 1}
    assert started.detail == {}
    # Every timestamp is Paris time, like the rest of the control plane.
    assert wake.occurred_at.utcoffset() == timedelta(hours=2)


def test_restarts_during_a_wake_do_not_repeat_the_online_event(
    repository: DistributedJobRepository, clock: Clock
) -> None:
    repository.register_worker(REGISTRATION)
    clock.now += timedelta(hours=1)
    repository.mark_worker_waking(WORKER, timeout_seconds=180)
    clock.now += timedelta(seconds=30)
    repository.register_worker(REGISTRATION)
    clock.now += timedelta(seconds=30)
    repository.register_worker(REGISTRATION)

    assert [event.kind.value for event in _events(repository)] == [
        "wake_sent",
        "worker_online",
    ]


def test_a_manual_start_leaves_no_power_event(
    repository: DistributedJobRepository, clock: Clock
) -> None:
    repository.register_worker(REGISTRATION)
    clock.now += timedelta(seconds=30)
    repository.register_worker(REGISTRATION)

    assert repository.list_workers().workers[0].power_events == []


def test_a_veto_is_recorded_with_its_reason(
    repository: DistributedJobRepository, clock: Clock
) -> None:
    repository.register_worker(REGISTRATION)
    clock.now += timedelta(hours=1)
    repository.mark_worker_waking(WORKER, timeout_seconds=180)
    repository.register_worker(REGISTRATION)
    assert _settle(repository).shutdown_requested is True

    repository.report_worker_power(
        {
            "protocol_version": 1,
            "worker_id": WORKER,
            "outcome": "shutdown_vetoed",
            "reason": "interactive_session",
            "sessions": 1,
        }
    )

    veto = repository.list_workers().workers[0].power_events[0]
    assert veto.kind.value == "shutdown_vetoed"
    assert veto.detail == {"reason": "interactive_session", "sessions": 1}
    # The permission is consumed: a vetoed PC is not stopped by a later poll.
    assert _settle(repository).shutdown_requested is False


def test_a_wake_failure_is_recorded(
    repository: DistributedJobRepository,
) -> None:
    repository.register_worker(REGISTRATION)

    repository.record_wake_failure(WORKER, "network unreachable", trigger="queued_jobs")

    event = repository.list_workers().workers[0].power_events[0]
    assert event.kind.value == "wake_failed"
    assert event.detail == {"trigger": "queued_jobs", "error": "network unreachable"}


def test_the_journal_is_bounded_per_worker(
    repository: DistributedJobRepository, clock: Clock
) -> None:
    repository.register_worker(REGISTRATION)
    for _ in range(230):
        repository.record_wake_failure(WORKER, "x", trigger="manual")

    with repository._lock:  # noqa: SLF001
        total = repository._connection.execute(  # noqa: SLF001
            "SELECT COUNT(*) FROM distributed_worker_power_events"
        ).fetchone()[0]
    assert total == 200
    assert len(repository.list_workers().workers[0].power_events) == 30


def test_a_report_for_an_unknown_worker_or_outcome_is_rejected(
    repository: DistributedJobRepository,
) -> None:
    with pytest.raises(LookupError):
        repository.report_worker_power(
            {
                "protocol_version": 1,
                "worker_id": "unknown",
                "outcome": "shutdown_started",
            }
        )
    repository.register_worker(REGISTRATION)
    with pytest.raises(ValueError):
        repository.report_worker_power(
            {"protocol_version": 1, "worker_id": WORKER, "outcome": "reboot"}
        )


def test_wake_failure_from_the_service_reaches_the_journal(
    tmp_path: Path, repository: DistributedJobRepository, clock: Clock
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(
        "infrastructure:\n  id: ohana-house\n  name: Ohana House\n"
        "  environment: production\nnodes: []\nservices: []\n",
        encoding="utf-8",
    )

    def broken_sender(_mac: str) -> None:
        raise OSError("network unreachable")

    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        job_repository=repository,
        wake_enabled=True,
        wake_sender=broken_sender,
        wake_retry_count=0,
    )
    repository.register_worker(REGISTRATION)
    clock.now += timedelta(hours=1)

    with pytest.raises(OSError):
        service.wake_worker(WORKER)

    event = repository.list_workers().workers[0].power_events[0]
    assert event.kind.value == "wake_failed"
    assert event.detail["trigger"] == "manual"


def test_worker_route_records_power_and_admin_list_exposes_it(
    tmp_path: Path, repository: DistributedJobRepository
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(
        "infrastructure:\n  id: ohana-house\n  name: Ohana House\n"
        "  environment: production\nnodes: []\nservices: []\n",
        encoding="utf-8",
    )
    repository.register_worker(REGISTRATION)
    server = AdministrationHTTPServer(
        service=AdministrationService(
            infrastructure_repository=InfrastructureConfigurationRepository(
                infrastructure_path
            ),
            job_repository=repository,
        ),
        token="tsunade-secret",
        worker_token="katsuyu-secret",
        port=0,
    )
    server.start()
    assert server.address is not None
    host, port = server.address
    base = f"http://{host}:{port}"

    def post(token: str) -> dict[str, object]:
        request = Request(
            f"{base}/v1/jobs/workers/power",
            data=json.dumps(
                {
                    "protocol_version": 1,
                    "worker_id": WORKER,
                    "outcome": "shutdown_vetoed",
                    "reason": "interactive_session",
                    "sessions": 2,
                }
            ).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return json.loads(response.read())

    try:
        with pytest.raises(HTTPError) as rejected:
            post("wrong-secret")
        recorded = post("katsuyu-secret")
        listing = Request(
            f"{base}/v1/jobs/workers",
            headers={"Authorization": "Bearer tsunade-secret"},
        )
        with urlopen(listing, timeout=2) as response:
            workers = json.loads(response.read())["workers"]
    finally:
        server.stop()

    assert rejected.value.code == 401
    assert recorded["outcome"] == "shutdown_vetoed"
    assert workers[0]["power_events"][0]["kind"] == "shutdown_vetoed"
    assert workers[0]["power_events"][0]["detail"] == {
        "reason": "interactive_session",
        "sessions": 2,
    }
