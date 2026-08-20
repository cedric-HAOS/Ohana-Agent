"""Tests for the minimal allowlisted Katsuyu worker."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from administration.katsuyu import KatsuyuHTTPClient, KatsuyuWorker, SystemHealthHandler
from administration.models import (
    DistributedJobClaimResult,
    DistributedJobDocument,
    DistributedJobStatus,
)
from plugins.mqtt.host_health import HostMetrics, SystemHostProbe


def metrics(**updates: Any) -> HostMetrics:
    values = {
        "hostname": "bubule",
        "operating_system": "Linux",
        "kernel": "6.12",
        "cpu_count": 4,
        "cpu_percent": 12.5,
        "load_1m_per_cpu": 0.2,
        "memory_percent": 40.0,
        "memory_total_bytes": 8 * 1024**3,
        "memory_available_bytes": 5 * 1024**3,
        "swap_percent": 0.0,
        "swap_total_bytes": 0,
        "swap_used_bytes": 0,
        "disk_percent": 25.0,
        "disk_free_bytes": 750 * 1024**3,
        "temperature_c": 45.0,
        "host_uptime_seconds": 1000,
        "agent_uptime_seconds": 10,
        "agent_restarts": None,
        "failed_systemd_units": (),
        "inactive_systemd_units": (),
    }
    values.update(updates)
    return HostMetrics(**values)


class FakeProbe:
    def __init__(self, result: HostMetrics) -> None:
        self.result = result
        self.calls = 0

    def collect(self) -> HostMetrics:
        self.calls += 1
        return self.result


def job_document() -> DistributedJobDocument:
    return DistributedJobDocument(
        job_id=uuid4(),
        type="system.health",
        created_at=datetime.now(UTC),
        parameters={},
        timeout=60,
        status=DistributedJobStatus.RUNNING,
        started_at=datetime.now(UTC),
        worker_id="katsuyu-bubule",
        attempt=1,
        lease_expires_at=datetime.now(UTC),
    )


class FakeClient:
    def __init__(self, job: DistributedJobDocument | None) -> None:
        self.job = job
        self.claims: list[dict[str, Any]] = []
        self.completions: list[tuple[str, dict[str, Any]]] = []

    def claim(self, payload: dict[str, Any]) -> DistributedJobClaimResult:
        self.claims.append(payload)
        return DistributedJobClaimResult(job=self.job)

    def complete(
        self,
        job_id: str,
        payload: dict[str, Any],
    ) -> DistributedJobDocument:
        self.completions.append((job_id, payload))
        return cast(DistributedJobDocument, self.job)


def test_system_health_handler_returns_strict_local_result() -> None:
    probe = FakeProbe(metrics())
    handler = SystemHealthHandler(
        probe=cast(SystemHostProbe, probe),
        disk_usage=lambda _path: SimpleNamespace(
            total=1000,
            used=250,
            free=750,
        ),
        sample_wait=lambda _seconds: None,
    )

    result = handler.execute({})

    assert result["status"] == "OK"
    assert result["platform"] == "Linux 6.12"
    assert result["cpu_percent"] == 12.5
    assert result["disk_total_bytes"] == 1000
    assert result["issues"] == []
    assert probe.calls == 2


def test_system_health_handler_reports_bounded_resource_issues() -> None:
    handler = SystemHealthHandler(
        probe=cast(
            SystemHostProbe,
            FakeProbe(
                metrics(
                    cpu_percent=90.0,
                    memory_percent=92.0,
                    temperature_c=80.0,
                )
            ),
        ),
        disk_usage=lambda _path: SimpleNamespace(total=1000, used=900, free=100),
        sample_wait=lambda _seconds: None,
    )

    result = handler.execute({})

    assert result["status"] == "DEGRADED"
    assert {issue["code"] for issue in result["issues"]} == {
        "resource.cpu.high",
        "resource.memory.high",
        "resource.disk.high",
        "resource.temperature.high",
    }


def test_worker_claims_only_declared_type_and_completes_success() -> None:
    client = FakeClient(job_document())
    handler = SystemHealthHandler(
        probe=cast(SystemHostProbe, FakeProbe(metrics())),
        disk_usage=lambda _path: SimpleNamespace(total=1000, used=250, free=750),
        sample_wait=lambda _seconds: None,
    )
    worker = KatsuyuWorker(
        client=cast(KatsuyuHTTPClient, client),
        worker_id="katsuyu-bubule",
        handlers={"system.health": handler},
    )

    assert worker.run_once() is True

    assert client.claims[0]["supported_types"] == ["system.health"]
    assert client.completions[0][1]["status"] == "SUCCEEDED"
    assert client.completions[0][1]["result"]["status"] == "OK"


def test_worker_reports_handler_failure_without_arbitrary_fallback() -> None:
    client = FakeClient(job_document())
    handler = SystemHealthHandler(
        probe=cast(SystemHostProbe, FakeProbe(metrics(memory_total_bytes=None))),
        disk_usage=lambda _path: SimpleNamespace(total=1000, used=250, free=750),
        sample_wait=lambda _seconds: None,
    )
    worker = KatsuyuWorker(
        client=cast(KatsuyuHTTPClient, client),
        worker_id="katsuyu-bubule",
        handlers={"system.health": handler},
    )

    assert worker.run_once() is True

    completion = client.completions[0][1]
    assert completion["status"] == "FAILED"
    assert completion["error"]["code"] == "handler.failed"
    assert completion["result"] is None


def test_worker_returns_without_completion_when_no_job_is_available() -> None:
    client = FakeClient(None)
    worker = KatsuyuWorker(
        client=cast(KatsuyuHTTPClient, client),
        worker_id="katsuyu-bubule",
    )

    assert worker.run_once() is False
    assert client.completions == []
