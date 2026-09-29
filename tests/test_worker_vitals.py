"""Phase 5: Katsuyu runtimes and last useful work per capability."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ohana_agent.api.http import AdministrationHTTPServer
from ohana_agent.api.service import AdministrationService
from ohana_agent.contracts.administration import DistributedJobStatus
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.jobs.repository import DistributedJobRepository

WORKER = "katsuyu-bubule"
REGISTRATION: dict[str, object] = {
    "protocol_version": 1,
    "worker_id": WORKER,
    "capabilities": ["system.health", "ai.inference"],
    "platform": "Windows 11",
    "worker_version": "0.9.1",
}
HEALTH_RESULT = {
    "status": "OK",
    "collected_at": "2026-08-19T08:00:00+00:00",
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
        self.now = datetime(2026, 9, 28, 16, 0, tzinfo=UTC)

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


def _run_health_job(
    repository: DistributedJobRepository,
    clock: Clock,
    job_id: str,
    *,
    succeed: bool,
) -> None:
    repository.create(
        {
            "protocol_version": 1,
            "job_id": job_id,
            "type": "system.health",
            "created_at": clock.now.isoformat(),
            "parameters": {},
            "timeout": 600,
        }
    )
    claimed = repository.claim(
        {
            "protocol_version": 1,
            "worker_id": WORKER,
            "supported_types": ["system.health"],
        }
    )
    assert claimed.job is not None
    clock.now += timedelta(seconds=30)
    repository.complete(
        job_id,
        {
            "protocol_version": 1,
            "worker_id": WORKER,
            "attempt": claimed.job.attempt,
            "status": "SUCCEEDED" if succeed else "FAILED",
            "result": HEALTH_RESULT if succeed else None,
            "error": (
                None
                if succeed
                else {
                    "code": "handler.failed",
                    "message": "probe failed",
                    "retryable": False,
                }
            ),
        },
    )


def _report(runtimes: dict[str, object]) -> dict[str, object]:
    return {"protocol_version": 1, "worker_id": WORKER, "runtimes": runtimes}


def test_registration_response_keeps_the_strict_katsuyu_shape(
    repository: DistributedJobRepository,
) -> None:
    registered = repository.register_worker(REGISTRATION)

    # Katsuyu 0.9.0 parses this document with extra="forbid".
    dumped = registered.model_dump(mode="json")
    assert "runtimes" not in dumped
    assert "activity" not in dumped


def test_registration_rejects_runtimes_to_keep_one_contract(
    repository: DistributedJobRepository,
) -> None:
    with pytest.raises(ValueError, match="runtimes"):
        repository.register_worker(
            {**REGISTRATION, "runtimes": {"ai.inference": {"state": "ready"}}}
        )


def test_runtimes_are_listed_only_for_announced_capabilities(
    repository: DistributedJobRepository,
    clock: Clock,
) -> None:
    repository.register_worker(REGISTRATION)
    clock.now += timedelta(minutes=2)
    reported = repository.report_worker_runtimes(
        _report(
            {
                "ai.inference": {"state": "missing", "detail": "llama-server absent"},
                "backup.encrypt": {"state": "ready"},
            }
        )
    )

    assert set(reported["runtimes"]) == {"ai.inference"}
    worker = repository.list_workers().workers[0]
    assert set(worker.runtimes) == {"ai.inference"}
    assert worker.runtimes["ai.inference"].state.value == "missing"
    assert worker.runtimes["ai.inference"].detail == "llama-server absent"
    assert worker.runtimes_reported_at == clock.now
    assert worker.last_seen_at == clock.now


def test_runtimes_are_unknown_until_reported_and_survive_registration(
    repository: DistributedJobRepository,
) -> None:
    repository.register_worker(REGISTRATION)
    assert repository.list_workers().workers[0].runtimes_reported_at is None

    repository.report_worker_runtimes(_report({"ai.inference": {"state": "ready"}}))
    repository.register_worker(REGISTRATION)

    worker = repository.list_workers().workers[0]
    assert worker.runtimes["ai.inference"].state.value == "ready"


def test_runtime_report_does_not_end_an_ohana_wake(
    repository: DistributedJobRepository,
    clock: Clock,
) -> None:
    repository.register_worker(REGISTRATION)
    clock.now += timedelta(minutes=5)
    repository.mark_worker_waking(WORKER, timeout_seconds=60)
    repository.register_worker(REGISTRATION)
    clock.now += timedelta(minutes=5)

    repository.report_worker_runtimes(_report({"ai.inference": {"state": "ready"}}))

    assert repository.list_workers().workers[0].woken_by_ohana is True


def test_runtime_report_rejects_unknown_worker_and_state(
    repository: DistributedJobRepository,
) -> None:
    with pytest.raises(LookupError):
        repository.report_worker_runtimes(_report({}))
    repository.register_worker(REGISTRATION)
    with pytest.raises(ValueError, match="state"):
        repository.report_worker_runtimes(_report({"ai.inference": {"state": "maybe"}}))


def test_activity_reports_last_success_and_last_failure_per_capability(
    repository: DistributedJobRepository,
    clock: Clock,
) -> None:
    repository.register_worker(REGISTRATION)
    _run_health_job(
        repository, clock, "11111111-1111-4111-8111-111111111111", succeed=True
    )
    succeeded_at = clock.now
    clock.now += timedelta(minutes=5)
    _run_health_job(
        repository, clock, "22222222-2222-4222-8222-222222222222", succeed=False
    )
    failed_at = clock.now

    worker = repository.list_workers().workers[0]
    activity = {item.type: item for item in worker.activity}
    assert set(activity) == {"ai.inference", "system.health"}
    health = activity["system.health"]
    assert health.last_succeeded_at == succeeded_at
    assert health.last_failed_at == failed_at
    assert health.last_failure_status == DistributedJobStatus.FAILED
    assert health.last_failure_message == "probe failed"
    never = activity["ai.inference"]
    assert never.last_succeeded_at is None
    assert never.last_failed_at is None


def test_activity_orders_by_instant_across_utc_offsets(
    repository: DistributedJobRepository,
    tmp_path: Path,
) -> None:
    """String order of Paris timestamps is wrong across the DST change."""
    repository.register_worker(REGISTRATION)
    connection = sqlite3.connect(tmp_path / "jobs.db")
    for job_id, finished_at in (
        # 02:30+01:00 (01:30 UTC) is later than 02:45+02:00 (00:45 UTC).
        ("33333333-3333-4333-8333-333333333333", "2026-10-25T02:30:00+01:00"),
        ("44444444-4444-4444-8444-444444444444", "2026-10-25T02:45:00+02:00"),
    ):
        connection.execute(
            """
            INSERT INTO distributed_jobs (
                job_id, protocol_version, type, created_at, parameters_json,
                timeout_seconds, status, finished_at, worker_id, request_sha256,
                updated_at
            ) VALUES (?, 1, 'system.health', ?, '{}', 600, 'SUCCEEDED', ?, ?,
                'x', ?)
            """,
            (job_id, finished_at, finished_at, WORKER, finished_at),
        )
    connection.commit()
    connection.close()

    worker = repository.list_workers().workers[0]
    health = next(item for item in worker.activity if item.type == "system.health")
    assert health.last_succeeded_at == datetime.fromisoformat(
        "2026-10-25T02:30:00+01:00"
    )


def test_worker_route_stores_runtimes_and_admin_list_exposes_them(
    tmp_path: Path,
    repository: DistributedJobRepository,
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
            f"{base}/v1/jobs/workers/runtimes",
            data=json.dumps(_report({"ai.inference": {"state": "ready"}})).encode(),
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
        reported = post("katsuyu-secret")
        listing = Request(
            f"{base}/v1/jobs/workers",
            headers={"Authorization": "Bearer tsunade-secret"},
        )
        with urlopen(listing, timeout=2) as response:
            workers = json.loads(response.read())["workers"]
    finally:
        server.stop()

    assert rejected.value.code == 401
    assert reported["runtimes"] == {"ai.inference": {"state": "ready", "detail": ""}}
    assert workers[0]["runtimes"]["ai.inference"]["state"] == "ready"
    assert {item["type"] for item in workers[0]["activity"]} == {
        "ai.inference",
        "system.health",
    }


def test_host_detail_is_kept_until_a_newer_report_brings_one(
    repository: DistributedJobRepository,
) -> None:
    # Phase 5 hardening: workspace, AI runtime detail and update state.
    repository.register_worker(REGISTRATION)
    report = _report({"ai.inference": {"state": "ready"}})
    report["host"] = {
        "workspace": {
            "path": "C:/ProgramData/Ohana/Katsuyu",
            "used_bytes": 1_000,
            "free_bytes": 50_000_000_000,
            "total_bytes": 500_000_000_000,
        },
        "ai": {
            "model": "ministral-3-14b",
            "model_bytes": 8_000_000_000,
            "model_verified": True,
            "runtime": "llama-server b6500",
            "last_inference_seconds": 42.5,
        },
        "update": {"latest_version": "0.12.0", "automatic": True, "state": "current"},
    }
    repository.report_worker_runtimes(report)
    # A report without host (older Katsuyu) keeps the last known detail.
    repository.report_worker_runtimes(_report({"ai.inference": {"state": "ready"}}))

    host = repository.list_workers().workers[0].host
    assert host is not None
    assert host.workspace.free_bytes == 50_000_000_000
    assert host.ai.runtime == "llama-server b6500"
    assert host.update.latest_version == "0.12.0"
