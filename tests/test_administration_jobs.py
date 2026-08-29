"""Tests for the durable Tsunade-to-Katsuyu job protocol."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
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
from administration.models import (
    AiInferenceParameters,
    AiInferenceResult,
    DistributedJobStatus,
)
from plugins.backup.backup_coordinator import BackupExecutionError

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


def typed_job_payload(
    clock: MutableClock,
    job_id: str,
    job_type: str,
    parameters: dict[str, object],
) -> dict[str, object]:
    return job_payload(
        clock,
        job_id=job_id,
        type=job_type,
        parameters=parameters,
    )


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


def test_ai_inference_contract_is_bounded_and_strict(
    repository: DistributedJobRepository,
    clock: MutableClock,
) -> None:
    created = repository.create(
        job_payload(
            clock,
            type="ai.inference",
            parameters={
                "task": "technical.diagnosis",
                "incident_id": "11111111-1111-4111-8111-111111111111",
                "question": "Qualifier cet intervalle.",
                "evidence": [{"source": "HA-01", "content": "health=OK"}],
                "max_output_tokens": 512,
            },
        )
    )

    assert created.type == "ai.inference"
    assert created.parameters["task"] == "technical.diagnosis"
    AiInferenceParameters.model_validate(
        {**created.parameters, "max_output_tokens": 16_384}
    )
    with pytest.raises(ValidationError):
        AiInferenceParameters.model_validate(
            {**created.parameters, "max_output_tokens": 16_385}
        )
    with pytest.raises(ValidationError):
        repository.create(
            job_payload(
                clock,
                job_id="22222222-2222-4222-8222-222222222222",
                type="ai.inference",
                parameters={
                    "task": "technical.diagnosis",
                    "incident_id": "11111111-1111-4111-8111-111111111111",
                    "question": "Exécuter ceci.",
                    "evidence": [{"source": "HA-01", "content": "OK"}],
                    "shell": "rm -rf /",
                },
            )
        )

    AiInferenceResult.model_validate(
        {
            "verdict": "OK",
            "generated_at": clock.now.isoformat(),
            "model_id": "ministral-3-14b-reasoning-2512-q4-k-m",
            "model_sha256": "f" * 64,
            "interpretation": "Les éléments bornés indiquent un état normal.",
            "summary": "Intervalle borné normal.",
            "findings": [],
            "hypotheses": [],
            "missing_context": [],
            "recommended_investigation": [],
            "metrics": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "ttft_ms": 100,
                "tokens_per_second": 80,
                "duration_seconds": 0.5,
            },
        }
    )


@pytest.mark.parametrize(
    ("overrides", "error_type"),
    [
        ({"type": "shell.execute"}, ValueError),
        (
            {"parameters": {"command": "uptime"}},
            ValidationError,
        ),
        ({"protocol_version": 2}, ValidationError),
        (
            {
                "type": "backup.compress",
                "parameters": {
                    "source": "../outside.tar",
                    "destination": "backup.tar.gz",
                },
            },
            ValidationError,
        ),
        (
            {
                "type": "backup.encrypt",
                "parameters": {
                    "source": "backup.tar.gz",
                    "destination": "backup.tar.gz",
                    "recipient": "age1" + "q" * 58,
                },
            },
            ValidationError,
        ),
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


def test_worker_registration_and_progress_survive_in_sqlite(
    repository: DistributedJobRepository,
    clock: MutableClock,
) -> None:
    registration = repository.register_worker(
        {
            "protocol_version": 1,
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health", "backup.verify"],
            "platform": "Windows 11",
            "worker_version": "1.15.2",
        }
    )
    assert registration.capabilities == ["backup.verify", "system.health"]
    assert registration.registered_at == clock.now
    assert registration.availability.value == "AVAILABLE"
    assert registration.woken_by_ohana is False

    repository.create(job_payload(clock))
    repository.claim(claim_payload())
    running = repository.heartbeat(
        JOB_ID,
        {
            "protocol_version": 1,
            "worker_id": "katsuyu-bubule",
            "attempt": 1,
            "progress": {
                "percent": 42.5,
                "stage": "system.sample",
                "message": "Mesure en cours",
            },
        },
    )
    assert running.progress is not None
    assert running.progress.percent == 42.5


def test_worker_registration_keeps_the_last_known_wake_on_lan_mac(
    repository: DistributedJobRepository,
) -> None:
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.8.3",
            "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
        }
    )

    registered = repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.8.3",
            "wake_on_lan_mac_address": None,
        }
    )

    assert registered.wake_on_lan_mac_address == "AA:BB:CC:DD:EE:FF"


def test_worker_registration_uses_the_configured_wake_on_lan_mac(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        job_repository=repository,
        wake_worker_id="katsuyu-bubule",
        wake_mac_address="AA:BB:CC:DD:EE:FF",
    )
    try:
        registered = service.register_worker(
            {
                "worker_id": "katsuyu-bubule",
                "capabilities": ["system.health"],
                "platform": "Windows 11",
                "worker_version": "0.8.3",
                "wake_on_lan_mac_address": None,
            }
        )

        assert registered.wake_on_lan_mac_address == "AA:BB:CC:DD:EE:FF"
    finally:
        repository.close()


def test_tsunade_uses_configured_mac_when_registered_worker_has_none(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(
        tmp_path / "jobs.db", clock=clock, worker_available_seconds=30
    )
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["logs.health_check"],
            "platform": "Windows 11",
            "worker_version": "0.8.3",
            "wake_on_lan_mac_address": None,
        }
    )
    clock.advance(31)
    sent: list[str] = []
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        job_repository=repository,
        wake_sender=sent.append,
        wake_enabled=True,
        wake_planned_window_end_hour=24,
        wake_worker_id="katsuyu-bubule",
        wake_mac_address="AA:BB:CC:DD:EE:FF",
    )
    try:
        service.create_job(
            typed_job_payload(
                clock,
                JOB_ID,
                "logs.health_check",
                {
                    "sources": ["ha-01"],
                    "window_started_at": (clock.now - timedelta(hours=24)).isoformat(),
                    "window_ended_at": clock.now.isoformat(),
                    "max_bytes_per_source": 1024,
                    "baseline": [],
                    "incident_id": None,
                },
            )
        )

        assert sent == ["AA:BB:CC:DD:EE:FF"]
        assert (
            repository.worker_availability("katsuyu-bubule").availability.value
            == "WAKING"
        )
    finally:
        repository.close()


def test_tsunade_wakes_only_an_unavailable_compatible_worker(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(
        tmp_path / "jobs.db", clock=clock, worker_available_seconds=30
    )
    clock.now = clock.now.replace(hour=0, minute=0, second=0, microsecond=0)
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["backup.infra"],
            "platform": "Windows 11",
            "worker_version": "0.3.0",
            "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
        }
    )
    clock.advance(31)
    sent: list[str] = []
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        job_repository=repository,
        wake_timeout_seconds=180,
        wake_sender=sent.append,
        wake_enabled=True,
        wake_batch_window_seconds=0,
        wake_planned_window_end_hour=24,
    )
    try:
        service.create_job(
            typed_job_payload(
                clock,
                JOB_ID,
                "backup.infra",
                {
                    "backup_id": "20260819T080000Z",
                    "recipient": "age1" + "q" * 58,
                    "compression_level": 6,
                },
            )
        )
        service.dispatch_due_wake_requests()
        worker = repository.worker_availability("katsuyu-bubule")
        assert sent == ["AA:BB:CC:DD:EE:FF"]
        assert worker.availability.value == "WAKING"
        assert worker.woken_by_ohana is True

        registered = repository.register_worker(
            {
                "worker_id": "katsuyu-bubule",
                "capabilities": ["backup.infra"],
                "platform": "Windows 11",
                "worker_version": "0.3.0",
                "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
            }
        )
        assert registered.availability.value == "AVAILABLE"
        assert registered.woken_by_ohana is True
    finally:
        repository.close()


def test_tsunade_groups_jobs_before_waking_worker(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(
        tmp_path / "jobs.db", clock=clock, worker_available_seconds=30
    )
    clock.now = clock.now.replace(hour=0, minute=0, second=0, microsecond=0)
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["backup.infra", "logs.health_check"],
            "platform": "Windows 11",
            "worker_version": "0.8.0",
            "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
        }
    )
    clock.advance(31)
    sent: list[str] = []
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        job_repository=repository,
        wake_timeout_seconds=180,
        wake_sender=sent.append,
        wake_enabled=True,
        wake_batch_window_seconds=600,
    )
    try:
        service.create_job(
            typed_job_payload(
                clock,
                JOB_ID,
                "backup.infra",
                {
                    "backup_id": "20260819T080000Z",
                    "recipient": "age1" + "q" * 58,
                    "compression_level": 6,
                },
            )
        )
        clock.advance(300)
        service.create_job(
            typed_job_payload(
                clock,
                "22222222-2222-4222-8222-222222222222",
                "logs.health_check",
                {
                    "sources": ["ha-01"],
                    "window_started_at": (
                        (clock.now - timedelta(hours=24)).isoformat()
                    ),
                    "window_ended_at": clock.now.isoformat(),
                    "max_bytes_per_source": 1048576,
                },
            )
        )

        assert sent == []

        clock.now = clock.now.replace(hour=3, minute=0, second=0, microsecond=0)
        service.dispatch_due_wake_requests(now=clock.now)

        assert sent == ["AA:BB:CC:DD:EE:FF"]
        assert (
            repository.worker_availability("katsuyu-bubule").availability.value
            == "WAKING"
        )
    finally:
        repository.close()


def test_tsunade_wakes_backup_worker_inside_planned_window_before_job_timeout(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(
        tmp_path / "jobs.db", clock=clock, worker_available_seconds=30
    )
    clock.now = clock.now.replace(hour=1, minute=59, second=29, microsecond=0)
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["backup.infra"],
            "platform": "Windows 11",
            "worker_version": "0.8.3",
            "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
        }
    )
    clock.advance(31)
    sent: list[str] = []
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        job_repository=repository,
        wake_timeout_seconds=180,
        wake_sender=sent.append,
        wake_enabled=True,
        wake_batch_window_seconds=600,
        wake_planned_window_start_hour=0,
        wake_planned_window_end_hour=5,
    )
    try:
        payload = typed_job_payload(
            clock,
            JOB_ID,
            "backup.infra",
            {
                "backup_id": "20260828T020000Z",
                "recipient": "age1" + "q" * 58,
                "compression_level": 6,
            },
        )
        payload["timeout"] = 3600
        service.create_job(payload)
        assert sent == []
        job = repository.get(JOB_ID)
        assert job.timeout == 7380

        clock.advance(600)
        service.dispatch_due_wake_requests(now=clock.now)
        assert sent == []

        clock.now = clock.now.replace(hour=3, minute=0, second=0, microsecond=0)
        service.dispatch_due_wake_requests(now=clock.now)
        worker = repository.worker_availability("katsuyu-bubule")
        job = repository.get(JOB_ID)
        assert sent == ["AA:BB:CC:DD:EE:FF"]
        assert worker.availability.value == "WAKING"
        assert job.status.value == "WAITING_WORKER"
    finally:
        repository.close()


def test_tsunade_does_not_wake_for_non_planned_worker_job(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(
        tmp_path / "jobs.db", clock=clock, worker_available_seconds=30
    )
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.8.0",
            "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
        }
    )
    clock.advance(31)
    sent: list[str] = []
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        job_repository=repository,
        wake_sender=sent.append,
        wake_enabled=True,
        wake_batch_window_seconds=0,
        wake_planned_window_end_hour=24,
    )
    try:
        service.create_job(job_payload(clock))
        service.dispatch_due_wake_requests()
        assert sent == []
    finally:
        repository.close()


def test_last_grouped_job_asks_ohana_woken_worker_to_shutdown(
    repository: DistributedJobRepository,
    clock: MutableClock,
) -> None:
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.8.0",
            "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
        }
    )
    repository.create(job_payload(clock))
    repository.create(
        job_payload(
            clock,
            job_id="22222222-2222-4222-8222-222222222222",
        )
    )
    clock.advance(31)
    repository.mark_worker_waking("katsuyu-bubule", timeout_seconds=180)
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.8.0",
            "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
        }
    )

    first = repository.claim(claim_payload()).job
    assert first is not None
    assert first.shutdown_after_completion is False
    repository.complete(str(first.job_id), success_payload(first.attempt))

    second = repository.claim(claim_payload()).job
    assert second is not None
    assert second.shutdown_after_completion is True


def test_human_started_worker_is_not_asked_to_shutdown(
    repository: DistributedJobRepository,
    clock: MutableClock,
) -> None:
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.8.0",
        }
    )
    repository.create(job_payload(clock))

    claimed = repository.claim(claim_payload()).job

    assert claimed is not None
    assert claimed.shutdown_after_completion is False


def test_wake_on_lan_policy_and_explicit_worker_wake(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(
        tmp_path / "jobs.db", clock=clock, worker_available_seconds=30
    )
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.7.0",
            "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
        }
    )
    clock.advance(31)
    sent: list[str] = []
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        job_repository=repository,
        wake_timeout_seconds=180,
        wake_sender=sent.append,
        wake_enabled=True,
        wake_broadcast_address="192.168.1.255",
        wake_port=9,
        wake_available_for_seconds=30,
        wake_packet_burst_count=3,
        wake_burst_interval_seconds=0.1,
        wake_retry_count=2,
        wake_retry_delay_seconds=1.0,
    )
    try:
        policy = service.read_wake_on_lan()
        assert policy == {
            "schema_version": 1,
            "enabled": True,
            "broadcast_address": "192.168.1.255",
            "port": 9,
            "wait_timeout_seconds": 180,
            "available_for_seconds": 30,
            "packet_burst_count": 3,
            "burst_interval_seconds": 0.1,
            "retry_count": 2,
            "retry_delay_seconds": 1.0,
            "batch_window_seconds": 600,
            "planned_window_start_hour": 0,
            "planned_window_end_hour": 5,
            "schedule_timezone": "Europe/Paris",
            "minimum_interval_seconds": 7200,
            "shutdown_after_completion": True,
        }
        worker = service.wake_worker("katsuyu-bubule")
        assert sent == ["AA:BB:CC:DD:EE:FF"]
        assert worker.availability.value == "WAKING"
        assert worker.woken_by_ohana is True
        assert "jobs.wake_on_lan.read" in service.capabilities().operations
        assert "jobs.workers.wake" in service.capabilities().operations
    finally:
        repository.close()


def test_log_analysis_policy_can_be_reconfigured(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
    changes = []
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        job_repository=repository,
        log_analysis_enabled=True,
        log_analysis_schedule="0 5 * * *",
        log_sources=("ha-01", "linky-01", "zwave-01"),
        on_log_analysis_changed=changes.append,
    )
    try:
        policy = service.read_log_analysis()
        assert policy["enabled"] is True
        assert policy["schedule"] == "0 5 * * *"
        assert policy["sources"] == ["ha-01", "linky-01", "zwave-01"]

        updated = service.write_log_analysis(
            {
                "enabled": False,
                "schedule": "30 6 * * *",
                "sources": ["ha-01"],
                "window_hours": 12,
                "max_bytes_per_source": 1048576,
                "timeout_seconds": 600,
            }
        )

        assert updated == {
            "schema_version": 1,
            "enabled": False,
            "schedule": "30 6 * * *",
            "sources": ["ha-01"],
            "window_hours": 12,
            "max_bytes_per_source": 1048576,
            "timeout_seconds": 600,
        }
        assert changes[-1].enabled is False
        with pytest.raises(LookupError, match="log analysis is unavailable"):
            service.request_log_health_check()
    finally:
        repository.close()


def test_wake_on_lan_retries_transient_sender_failures(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(
        tmp_path / "jobs.db", clock=clock, worker_available_seconds=30
    )
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.7.0",
            "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
        }
    )
    clock.advance(31)
    attempts: list[str] = []
    sleeps: list[float] = []

    def wake_sender(mac_address: str) -> None:
        attempts.append(mac_address)
        if len(attempts) < 3:
            raise OSError("temporary broadcast failure")

    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        job_repository=repository,
        wake_timeout_seconds=180,
        wake_sender=wake_sender,
        wake_enabled=True,
        wake_retry_count=2,
        wake_retry_delay_seconds=0.5,
        wake_retry_sleeper=sleeps.append,
    )
    try:
        worker = service.wake_worker("katsuyu-bubule")
        assert attempts == [
            "AA:BB:CC:DD:EE:FF",
            "AA:BB:CC:DD:EE:FF",
            "AA:BB:CC:DD:EE:FF",
        ]
        assert sleeps == [0.5, 0.5]
        assert worker.availability.value == "WAKING"
    finally:
        repository.close()


def test_explicit_worker_wake_is_rejected_when_wol_is_disabled(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.7.0",
            "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
        }
    )
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            infrastructure_path
        ),
        job_repository=repository,
        wake_broadcast_address="192.168.1.255",
    )
    try:
        assert service.read_wake_on_lan()["enabled"] is False
        assert "jobs.wake_on_lan.read" in service.capabilities().operations
        assert "jobs.workers.wake" not in service.capabilities().operations
        with pytest.raises(DistributedJobConflictError, match="disabled"):
            service.wake_worker("katsuyu-bubule")
    finally:
        repository.close()


def test_spontaneous_worker_registration_is_never_marked_woken_by_ohana(
    repository: DistributedJobRepository,
    clock: MutableClock,
) -> None:
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.3.0",
        }
    )
    clock.advance(31)
    assert (
        repository.worker_availability("katsuyu-bubule").availability.value
        == "UNAVAILABLE"
    )
    registered = repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.3.0",
        }
    )
    assert registered.woken_by_ohana is False


def test_registration_after_wake_deadline_is_treated_as_human_start(
    repository: DistributedJobRepository,
    clock: MutableClock,
) -> None:
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.3.0",
        }
    )
    clock.advance(31)
    repository.mark_worker_waking("katsuyu-bubule", timeout_seconds=180)
    clock.advance(181)
    registered = repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.3.0",
        }
    )
    assert registered.woken_by_ohana is False
    assert registered.wake_requested_at is None


def test_heartbeat_observes_tsunade_cancellation(
    repository: DistributedJobRepository,
    clock: MutableClock,
) -> None:
    repository.create(job_payload(clock))
    repository.claim(claim_payload())
    repository.cancel(JOB_ID)

    observed = repository.heartbeat(
        JOB_ID,
        {
            "protocol_version": 1,
            "worker_id": "katsuyu-bubule",
            "attempt": 1,
        },
    )

    assert observed.status == DistributedJobStatus.CANCELLED
    with pytest.raises(DistributedJobConflictError):
        repository.heartbeat(
            JOB_ID,
            {
                "protocol_version": 1,
                "worker_id": "katsuyu-other",
                "attempt": 1,
            },
        )


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


def test_worker_pairing_issues_one_bound_credential(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    repository = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
    try:
        created = repository.create_pairing(
            {
                "protocol_version": 1,
                "worker_id": "katsuyu-bubule",
                "capabilities": ["system.health"],
                "platform": "Windows 11",
                "worker_version": "0.1.0",
            }
        )
        assert created.verification_code
        assert repository.list_pairings().pairings[0].status == "PENDING"

        pending = repository.poll_pairing(
            str(created.pairing_id),
            {"protocol_version": 1, "polling_secret": created.polling_secret},
        )
        assert pending.status == "PENDING"
        assert pending.worker_token is None

        repository.approve_pairing(str(created.pairing_id))
        consumed = repository.poll_pairing(
            str(created.pairing_id),
            {"protocol_version": 1, "polling_secret": created.polling_secret},
        )
        assert consumed.status == "CONSUMED"
        assert consumed.worker_token is not None
        assert repository.authorize_worker("katsuyu-bubule", consumed.worker_token)
        assert not repository.authorize_worker("another-worker", consumed.worker_token)

        repeated = repository.poll_pairing(
            str(created.pairing_id),
            {"protocol_version": 1, "polling_secret": created.polling_secret},
        )
        assert repeated.status == "CONSUMED"
        assert repeated.worker_token is None
    finally:
        repository.close()


def test_worker_identity_migration_preserves_pairing_credential(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    repository = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
    try:
        created = repository.create_pairing(
            {
                "worker_id": "katsuyu-Bubule",
                "capabilities": ["system.health"],
                "platform": "Windows 11",
                "worker_version": "0.6.3",
            }
        )
        repository.approve_pairing(str(created.pairing_id))
        consumed = repository.poll_pairing(
            str(created.pairing_id),
            {"polling_secret": created.polling_secret},
        )
        assert consumed.worker_token is not None
        token = consumed.worker_token
        repository.register_worker(
            {
                "worker_id": "katsuyu-Bubule",
                "capabilities": ["system.health"],
                "platform": "Windows 11",
                "worker_version": "0.6.3",
            }
        )

        assert repository.authorize_worker(
            "katsuyu-bubule",
            token,
            previous_worker_id="katsuyu-Bubule",
        )
        migrated = repository.register_worker(
            {
                "worker_id": "katsuyu-bubule",
                "capabilities": ["system.health"],
                "platform": "Windows 11",
                "worker_version": "0.6.4",
                "wake_on_lan_mac_address": "aa-bb-cc-dd-ee-ff",
            },
            previous_worker_id="katsuyu-Bubule",
        )

        assert migrated.worker_id == "katsuyu-bubule"
        assert migrated.wake_on_lan_mac_address == "AA:BB:CC:DD:EE:FF"
        assert repository.authorize_worker("katsuyu-bubule", token)
        assert not repository.authorize_worker("katsuyu-Bubule", token)
        assert [worker.worker_id for worker in repository.list_workers().workers] == [
            "katsuyu-bubule"
        ]
    finally:
        repository.close()


def test_existing_worker_table_is_extended_with_wake_on_lan_mac(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    database = tmp_path / "jobs.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE distributed_workers (
            worker_id TEXT PRIMARY KEY,
            protocol_version INTEGER NOT NULL,
            capabilities_json TEXT NOT NULL,
            platform TEXT NOT NULL,
            worker_version TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            woken_by_ohana INTEGER NOT NULL DEFAULT 0,
            wake_requested_at TEXT,
            wake_deadline_at TEXT
        )
        """
    )
    connection.commit()
    connection.close()

    repository = DistributedJobRepository(database, clock=clock)
    try:
        worker = repository.register_worker(
            {
                "worker_id": "katsuyu-bubule",
                "capabilities": ["system.health"],
                "platform": "Windows 11",
                "worker_version": "0.7.0",
                "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
            }
        )
        assert worker.wake_on_lan_mac_address == "AA:BB:CC:DD:EE:FF"
    finally:
        repository.close()


def test_worker_pairing_expires_without_approval(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    repository = DistributedJobRepository(
        tmp_path / "jobs.db", clock=clock, pairing_ttl_seconds=60
    )
    try:
        created = repository.create_pairing(
            {
                "worker_id": "katsuyu-bubule",
                "capabilities": ["system.health"],
                "platform": "Windows 11",
                "worker_version": "0.1.0",
            }
        )
        clock.now += timedelta(seconds=61)
        result = repository.poll_pairing(
            str(created.pairing_id),
            {"polling_secret": created.polling_secret},
        )
        assert result.status == "EXPIRED"
        assert result.worker_token is None
    finally:
        repository.close()


def _request_json(
    server: AdministrationHTTPServer,
    path: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
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
            **(headers or {}),
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
        registered = _request_json(
            server,
            "/v1/jobs/workers/register",
            token="katsuyu-secret",
            method="POST",
            payload={
                "protocol_version": 1,
                "worker_id": "katsuyu-bubule",
                "capabilities": ["system.health"],
                "platform": "Windows 11",
                "worker_version": "1.15.2",
            },
        )
        workers = _request_json(
            server,
            "/v1/jobs/workers",
            token="tsunade-secret",
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
    assert "jobs.worker.register" in capabilities["operations"]
    assert "jobs.workers.read" in capabilities["operations"]
    assert created["status"] == "QUEUED"
    assert registered["worker_id"] == "katsuyu-bubule"
    assert workers["workers"][0]["capabilities"] == ["system.health"]  # type: ignore[index]
    assert management_on_worker.value.code == 401
    assert worker_on_management.value.code == 401
    assert claimed["job"]["status"] == "RUNNING"  # type: ignore[index]
    assert completed["status"] == "SUCCEEDED"


def test_http_pairing_requires_tsunade_approval_and_binds_worker_token(
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
        worker_token="legacy-katsuyu-secret",
        port=0,
    )
    server.start()
    try:
        pairing = _request_json(
            server,
            "/v1/jobs/workers/pairings",
            token="",
            method="POST",
            payload={
                "worker_id": "katsuyu-bubule",
                "capabilities": ["system.health"],
                "platform": "Windows 11",
                "worker_version": "0.1.0",
            },
        )
        pairing_id = str(pairing["pairing_id"])
        polling_secret = str(pairing["polling_secret"])
        listed = _request_json(
            server,
            "/v1/jobs/workers/pairings",
            token="tsunade-secret",
        )
        assert "polling_secret" not in listed["pairings"][0]  # type: ignore[index]
        assert "worker_token" not in listed["pairings"][0]  # type: ignore[index]

        _request_json(
            server,
            f"/v1/jobs/workers/pairings/{pairing_id}/approve",
            token="tsunade-secret",
            method="POST",
        )
        result = _request_json(
            server,
            f"/v1/jobs/workers/pairings/{pairing_id}/poll",
            token="",
            method="POST",
            payload={"polling_secret": polling_secret},
        )
        worker_token = str(result["worker_token"])
        registered = _request_json(
            server,
            "/v1/jobs/workers/register",
            token=worker_token,
            method="POST",
            payload={
                "worker_id": "katsuyu-bubule",
                "capabilities": ["system.health"],
                "platform": "Windows 11",
                "worker_version": "0.1.0",
            },
        )
        assert registered["worker_id"] == "katsuyu-bubule"

        with pytest.raises(HTTPError) as wrong_worker:
            _request_json(
                server,
                "/v1/jobs/workers/register",
                token=worker_token,
                method="POST",
                payload={
                    "worker_id": "katsuyu-other",
                    "capabilities": ["system.health"],
                    "platform": "Windows 11",
                    "worker_version": "0.1.0",
                },
            )
        assert wrong_worker.value.code == 401
    finally:
        server.stop()
        repository.close()


def test_http_registration_can_migrate_only_the_authenticated_previous_worker(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
    created = repository.create_pairing(
        {
            "worker_id": "katsuyu-Bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.6.3",
        }
    )
    repository.approve_pairing(str(created.pairing_id))
    consumed = repository.poll_pairing(
        str(created.pairing_id),
        {"polling_secret": created.polling_secret},
    )
    assert consumed.worker_token is not None
    token = consumed.worker_token
    repository.register_worker(
        {
            "worker_id": "katsuyu-Bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.6.3",
        }
    )
    server = AdministrationHTTPServer(
        service=AdministrationService(
            infrastructure_repository=InfrastructureConfigurationRepository(
                infrastructure_path
            ),
            job_repository=repository,
        ),
        token="tsunade-secret",
        worker_token="legacy-shared",
        port=0,
    )
    server.start()
    try:
        with pytest.raises(HTTPError) as shared_token_migration:
            _request_json(
                server,
                "/v1/jobs/workers/register",
                token="legacy-shared",
                method="POST",
                headers={"X-Ohana-Previous-Worker-Id": "katsuyu-Bubule"},
                payload={
                    "worker_id": "katsuyu-bubule",
                    "capabilities": ["system.health"],
                    "platform": "Windows 11",
                    "worker_version": "0.7.0",
                },
            )
        assert shared_token_migration.value.code == 401

        migrated = _request_json(
            server,
            "/v1/jobs/workers/register",
            token=token,
            method="POST",
            headers={"X-Ohana-Previous-Worker-Id": "katsuyu-Bubule"},
            payload={
                "worker_id": "katsuyu-bubule",
                "capabilities": ["system.health"],
                "platform": "Windows 11",
                "worker_version": "0.6.4",
                "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
            },
        )
        assert migrated["worker_id"] == "katsuyu-bubule"

        with pytest.raises(HTTPError) as wrong_previous:
            _request_json(
                server,
                "/v1/jobs/workers/register",
                token=token,
                method="POST",
                headers={"X-Ohana-Previous-Worker-Id": "katsuyu-other"},
                payload={
                    "worker_id": "katsuyu-new",
                    "capabilities": ["system.health"],
                    "platform": "Windows 11",
                    "worker_version": "0.6.4",
                },
            )
        assert wrong_previous.value.code == 401
    finally:
        server.stop()
        repository.close()


def test_worker_listener_exposes_only_worker_routes(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
    fingerprint = "a" * 64
    server = AdministrationHTTPServer(
        service=AdministrationService(
            infrastructure_repository=InfrastructureConfigurationRepository(
                infrastructure_path
            ),
            job_repository=repository,
            worker_ca_certificate_pem="test public CA",
            worker_ca_sha256=fingerprint,
        ),
        token="tsunade-secret",
        worker_token=None,
        worker_only=True,
        port=0,
    )
    server.start()
    try:
        trust = _request_json(
            server,
            "/v1/jobs/workers/trust",
            token="",
        )
        with pytest.raises(HTTPError) as capabilities:
            _request_json(
                server,
                "/v1/capabilities",
                token="tsunade-secret",
            )
        with pytest.raises(HTTPError) as create_job:
            _request_json(
                server,
                "/v1/jobs",
                token="tsunade-secret",
                method="POST",
                payload=job_payload(clock),
            )
        with pytest.raises(HTTPError) as shared_worker_token:
            _request_json(
                server,
                "/v1/jobs/workers/register",
                token="katsuyu-secret",
                method="POST",
                payload={
                    "protocol_version": 1,
                    "worker_id": "katsuyu-bubule",
                    "capabilities": ["system.health"],
                    "platform": "Windows 11",
                    "worker_version": "0.1.0",
                },
            )
    finally:
        server.stop()
        repository.close()

    assert trust["ca_sha256"] == fingerprint
    assert capabilities.value.code == 404
    assert create_job.value.code == 404
    assert shared_worker_token.value.code == 401


def test_worker_backup_source_preparation_fails_before_http_200(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    class FailingBackupTransfer:
        @contextmanager
        def open_source(self, _job_id: str, _worker_id: str, _attempt: int) -> object:
            raise BackupExecutionError("storage", "database or disk is full")
            yield  # pragma: no cover

    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(tmp_path / "jobs.db", clock=clock)
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["backup.infra"],
            "platform": "Windows 11",
            "worker_version": "0.3.1",
        }
    )
    repository.create(
        job_payload(
            clock,
            type="backup.infra",
            parameters={
                "backup_id": "20260821T074700Z",
                "recipient": "age1" + "q" * 58,
                "compression_level": 6,
            },
            timeout=600,
        )
    )
    claimed = repository.claim(
        {
            "worker_id": "katsuyu-bubule",
            "supported_types": ["backup.infra"],
        }
    )
    assert claimed.job is not None
    server = AdministrationHTTPServer(
        service=AdministrationService(
            infrastructure_repository=InfrastructureConfigurationRepository(
                infrastructure_path
            ),
            job_repository=repository,
            backup_transfer=FailingBackupTransfer(),
        ),
        token="tsunade-secret",
        worker_token="katsuyu-secret",
        worker_only=True,
        port=0,
    )
    server.start()
    assert server.address is not None
    host, port = server.address
    request = Request(
        f"http://{host}:{port}/v1/jobs/{JOB_ID}/input",
        headers={
            "Authorization": "Bearer katsuyu-secret",
            "X-Ohana-Worker-Id": "katsuyu-bubule",
            "X-Ohana-Attempt": "1",
        },
    )
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=2)
        detail = json.loads(error.value.read())
    finally:
        server.stop()
        repository.close()

    assert error.value.code == 507
    assert detail == {
        "detail": (
            "Distributed backup source preparation failed: database or disk is full"
        )
    }


def test_http_routes_expose_wake_policy_and_explicit_wake(
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    infrastructure_path = tmp_path / "infrastructure.yaml"
    infrastructure_path.write_text(INFRASTRUCTURE_YAML, encoding="utf-8")
    repository = DistributedJobRepository(
        tmp_path / "jobs.db", clock=clock, worker_available_seconds=30
    )
    repository.register_worker(
        {
            "worker_id": "katsuyu-bubule",
            "capabilities": ["system.health"],
            "platform": "Windows 11",
            "worker_version": "0.7.0",
            "wake_on_lan_mac_address": "AA:BB:CC:DD:EE:FF",
        }
    )
    clock.advance(31)
    sent: list[str] = []
    server = AdministrationHTTPServer(
        service=AdministrationService(
            infrastructure_repository=InfrastructureConfigurationRepository(
                infrastructure_path
            ),
            job_repository=repository,
            wake_timeout_seconds=180,
            wake_sender=sent.append,
            wake_enabled=True,
            wake_broadcast_address="192.168.1.255",
            wake_port=9,
            wake_available_for_seconds=30,
        ),
        token="tsunade-secret",
        worker_token="katsuyu-secret",
        port=0,
    )
    server.start()
    try:
        policy = _request_json(
            server,
            "/v1/jobs/wake-on-lan",
            token="tsunade-secret",
        )
        worker = _request_json(
            server,
            "/v1/jobs/workers/katsuyu-bubule/wake",
            token="tsunade-secret",
            method="POST",
        )
    finally:
        server.stop()
        repository.close()

    assert policy["enabled"] is True
    assert policy["broadcast_address"] == "192.168.1.255"
    assert worker["availability"] == "WAKING"
    assert worker["woken_by_ohana"] is True
    assert sent == ["AA:BB:CC:DD:EE:FF"]
