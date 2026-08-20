"""Tests for the durable Tsunade-to-Katsuyu job protocol."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from pydantic import ValidationError

from administration import (
    AdministrationHTTPServer,
    AdministrationService,
    DistributedJobConflictError,
    DistributedJobRepository,
    InfrastructureConfigurationRepository,
)
from administration.models import DistributedJobStatus

JOB_ID = "11111111-1111-4111-8111-111111111111"
INFRASTRUCTURE_YAML = """\
infrastructure:
  id: ohana-house
  name: Ohana House
  environment: production
nodes: []
services: []
"""


class MutableClock:
    """Timezone-aware clock advanced explicitly by each recovery test."""

    def __init__(self) -> None:
        self.now = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def job_payload(clock: MutableClock, **overrides: object) -> dict[str, object]:
    """Build one valid, deterministic system-health request."""
    payload: dict[str, object] = {
        "protocol_version": 1,
        "job_id": JOB_ID,
        "type": "system.health",
        "created_at": clock.now.isoformat(),
        "parameters": {},
        "timeout": 600,
    }
    payload.update(overrides)
    return payload


def claim_payload(worker_id: str = "katsuyu-bubule") -> dict[str, object]:
    return {
        "protocol_version": 1,
        "worker_id": worker_id,
        "supported_types": ["system.health"],
    }


def success_payload(attempt: int = 1) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "worker_id": "katsuyu-bubule",
        "attempt": attempt,
        "status": "SUCCEEDED",
        "result": {
            "status": "OK",
            "collected_at": "2026-08-19T08:00:00+00:00",
            "platform": "Linux",
            "cpu_percent": 12.5,
            "memory_total_bytes": 1_073_741_824,
            "memory_available_bytes": 536_870_912,
            "disk_total_bytes": 32_000_000_000,
            "disk_free_bytes": 16_000_000_000,
            "temperature_c": 48.5,
            "issues": [],
        },
        "error": None,
    }


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock()


@pytest.fixture
def repository(tmp_path: Path, clock: MutableClock) -> DistributedJobRepository:
    instance = DistributedJobRepository(
        tmp_path / "jobs.db",
        lease_seconds=30,
        waiting_worker_after_seconds=10,
        clock=clock,
    )
    yield instance
    instance.close()


def test_create_is_idempotent_and_rejects_changed_duplicate(
    repository: DistributedJobRepository,
    clock: MutableClock,
) -> None:
    created = repository.create(job_payload(clock))
    duplicate = repository.create(job_payload(clock))

    assert created.status == DistributedJobStatus.QUEUED
    assert duplicate == created
    assert created.protocol_version == 1
    assert created.type == "system.health"
    assert created.parameters == {}

    with pytest.raises(DistributedJobConflictError):
        repository.create(job_payload(clock, timeout=601))


@pytest.mark.parametrize(
    ("overrides", "error_type"),
    [
        ({"type": "shell.execute"}, ValueError),
        (
            {"parameters": {"command": "uptime"}},
            ValidationError,
        ),
        ({"protocol_version": 2}, ValidationError),
    ],
)
def test_create_rejects_undeclared_types_and_invalid_parameters(
    repository: DistributedJobRepository,
    clock: MutableClock,
    overrides: dict[str, object],
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        repository.create(job_payload(clock, **overrides))


def test_claim_heartbeat_and_verified_completion(
    repository: DistributedJobRepository,
    clock: MutableClock,
) -> None:
    repository.create(job_payload(clock))
    claim = repository.claim(claim_payload())

    assert claim.job is not None
    assert claim.job.status == DistributedJobStatus.RUNNING
    assert claim.job.attempt == 1
    assert claim.job.worker_id == "katsuyu-bubule"

    clock.advance(10)
    heartbeat = repository.heartbeat(
        JOB_ID,
        {
            "protocol_version": 1,
            "worker_id": "katsuyu-bubule",
            "attempt": 1,
        },
    )
    assert heartbeat.lease_expires_at == clock.now + timedelta(seconds=30)

    completed = repository.complete(JOB_ID, success_payload())
    expected_result = {
        "status": "OK",
        "collected_at": "2026-08-19T08:00:00Z",
        "platform": "Linux",
        "cpu_percent": 12.5,
        "memory_total_bytes": 1_073_741_824,
        "memory_available_bytes": 536_870_912,
        "disk_total_bytes": 32_000_000_000,
        "disk_free_bytes": 16_000_000_000,
        "temperature_c": 48.5,
        "issues": [],
    }
    expected_digest = hashlib.sha256(
        json.dumps(
            expected_result,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert completed.status == DistributedJobStatus.SUCCEEDED
    assert completed.result == expected_result
    assert completed.result_sha256 == expected_digest
    assert completed.finished_at == clock.now
    assert repository.complete(JOB_ID, success_payload()) == completed


@pytest.mark.parametrize(
    "result",
    [
        {
            **success_payload()["result"],  # type: ignore[dict-item]
            "memory_available_bytes": 2_000_000_000,
        },
        {
            **success_payload()["result"],  # type: ignore[dict-item]
            "status": "DEGRADED",
            "issues": [],
        },
        {
            **success_payload()["result"],  # type: ignore[dict-item]
            "status": "OK",
            "issues": [
                {
                    "code": "memory.low",
                    "message": "Available memory is below the safe threshold.",
                }
            ],
        },
    ],
)
def test_completion_rejects_inconsistent_system_health_results(
    repository: DistributedJobRepository,
    clock: MutableClock,
    result: dict[str, object],
) -> None:
    repository.create(job_payload(clock))
    repository.claim(claim_payload())
    payload = success_payload()
    payload["result"] = result

    with pytest.raises(ValidationError):
        repository.complete(JOB_ID, payload)


def test_expired_lease_is_requeued_for_a_new_attempt(
    repository: DistributedJobRepository,
    clock: MutableClock,
) -> None:
    repository.create(job_payload(clock))
    first = repository.claim(claim_payload())
    assert first.job is not None

    clock.advance(31)
    second = repository.claim(claim_payload("katsuyu-restarted"))
    assert second.job is not None
    assert second.job.attempt == 2
    assert second.job.worker_id == "katsuyu-restarted"

    with pytest.raises(DistributedJobConflictError):
        repository.heartbeat(
            JOB_ID,
            {
                "protocol_version": 1,
                "worker_id": "katsuyu-bubule",
                "attempt": 1,
            },
        )


def test_waiting_timeout_and_cancellation_are_terminal(
    repository: DistributedJobRepository,
    clock: MutableClock,
) -> None:
    repository.create(job_payload(clock, timeout=60))
    clock.advance(11)
    assert repository.get(JOB_ID).status == DistributedJobStatus.WAITING_WORKER

    cancelled = repository.cancel(JOB_ID)
    assert cancelled.status == DistributedJobStatus.CANCELLED
    assert repository.cancel(JOB_ID) == cancelled

    timeout_id = "22222222-2222-4222-8222-222222222222"
    repository.create(job_payload(clock, job_id=timeout_id, timeout=60))
    clock.advance(61)
    timed_out = repository.get(timeout_id)
    assert timed_out.status == DistributedJobStatus.TIMEOUT
    assert timed_out.finished_at == clock.now


def test_active_queue_is_bounded(tmp_path: Path, clock: MutableClock) -> None:
    repository = DistributedJobRepository(
        tmp_path / "bounded.db",
        max_active_jobs=1,
        clock=clock,
    )
    try:
        repository.create(job_payload(clock))
        with pytest.raises(ValueError, match="active queue limit"):
            repository.create(
                job_payload(
                    clock,
                    job_id="33333333-3333-4333-8333-333333333333",
                )
            )
    finally:
        repository.close()


def test_terminal_jobs_are_purged_after_retention(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    repository = DistributedJobRepository(
        tmp_path / "retention.db",
        retention_days=1,
        clock=clock,
    )
    try:
        repository.create(job_payload(clock))
        repository.claim(claim_payload())
        repository.complete(JOB_ID, success_payload())
        clock.advance(86_401)
        replacement_id = "44444444-4444-4444-8444-444444444444"
        repository.create(job_payload(clock, job_id=replacement_id))
        with pytest.raises(LookupError):
            repository.get(JOB_ID)
    finally:
        repository.close()


def test_server_requires_distinct_worker_credentials(
    tmp_path: Path,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(tmp_path / "jobs.db")
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        job_repository=repository,
    )
    try:
        with pytest.raises(ValueError, match="must be different"):
            AdministrationHTTPServer(service=service, token="same", worker_token="same")
    finally:
        repository.close()


def _request_json(
    server: AdministrationHTTPServer,
    path: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    assert server.address is not None
    host, port = server.address
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        f"http://{host}:{port}{path}",
        method=method,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    with urlopen(request, timeout=2) as response:
        result = json.load(response)
    assert isinstance(result, dict)
    return result


def test_http_routes_keep_tsunade_and_katsuyu_permissions_separate(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
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
    try:
        capabilities = _request_json(
            server,
            "/v1/capabilities",
            token="tsunade-secret",
        )
        created = _request_json(
            server,
            "/v1/jobs",
            token="tsunade-secret",
            method="POST",
            payload=job_payload(clock),
        )
        with pytest.raises(HTTPError) as management_on_worker:
            _request_json(
                server,
                "/v1/jobs/claim",
                token="tsunade-secret",
                method="POST",
                payload=claim_payload(),
            )
        with pytest.raises(HTTPError) as worker_on_management:
            _request_json(
                server,
                f"/v1/jobs/{JOB_ID}",
                token="katsuyu-secret",
            )
        claimed = _request_json(
            server,
            "/v1/jobs/claim",
            token="katsuyu-secret",
            method="POST",
            payload=claim_payload(),
        )
        completed = _request_json(
            server,
            f"/v1/jobs/{JOB_ID}/complete",
            token="katsuyu-secret",
            method="POST",
            payload=success_payload(),
        )
    finally:
        server.stop()
        repository.close()

    assert "jobs.create" in capabilities["operations"]
    assert created["status"] == "QUEUED"
    assert management_on_worker.value.code == 401
    assert worker_on_management.value.code == 401
    assert claimed["job"]["status"] == "RUNNING"  # type: ignore[index]
    assert completed["status"] == "SUCCEEDED"
