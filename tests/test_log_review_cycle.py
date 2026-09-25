"""End-to-end daily log review and idle shutdown, with durable recovery."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.api.http import AdministrationHTTPServer
from ohana_agent.api.service import AdministrationService
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.jobs.repository import DistributedJobRepository
from ohana_agent.tsunade.expertise import (
    TsunadeExpertiseService,
)
from ohana_agent.tsunade.incident_summary import incident_assessment
from ohana_agent.tsunade.incidents import (
    TsunadeIncidentRepository,
)


class NoProbes:
    def execute(self, _payload):
        raise AssertionError("daily review must reuse collected logs")


@pytest.fixture
def cycle(tmp_path: Path):
    now = [datetime.now(ZoneInfo("Europe/Paris"))]
    jobs = DistributedJobRepository(tmp_path / "jobs.db", clock=lambda: now[0])
    incidents = TsunadeIncidentRepository(tmp_path / "incidents.db")
    expertise = TsunadeExpertiseService(
        incidents=incidents, investigations=NoProbes(), ai_dispatcher=jobs.create
    )
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infrastructure.yaml"
        ),
        job_repository=jobs,
        incident_repository=incidents,
        expertise_service=expertise,
    )
    registration = {
        "worker_id": "katsuyu-test",
        "platform": "Windows",
        "worker_version": "test",
        "capabilities": ["logs.health_check", "ai.inference"],
    }
    jobs.register_worker(registration)
    now[0] += timedelta(seconds=31)
    jobs.mark_worker_waking("katsuyu-test", timeout_seconds=180)
    jobs.register_worker(registration)
    yield service, jobs, incidents, now
    jobs.close()
    incidents.close()


def test_historical_baseline_is_redacted_before_job_persistence(
    cycle, monkeypatch, tmp_path
):
    service, jobs, _incidents, now = cycle
    service.log_analysis_enabled = True
    service.log_sources = ("ha-01",)
    secrets = ("legacy.private*One!", "legacy.private*Two!")
    previous = {
        "sources": [
            {
                "source": "ha-01",
                "findings": [
                    {
                        "signature": f"connection failed /stok={secret}/ds",
                        "occurrences": count,
                    }
                    for secret, count in zip(secrets, (3, 5), strict=True)
                ],
            }
        ]
    }
    monkeypatch.setattr(
        jobs,
        "latest_log_health_sources",
        lambda _sources, **_kwargs: previous["sources"],
    )
    created = service.request_log_health_check(now=now[0])
    # A fresh connection sees only masked parameters, before any worker runs.
    reopened = DistributedJobRepository(tmp_path / "jobs.db")
    try:
        persisted = reopened.get(str(created.job_id))
    finally:
        reopened.close()
    encoded = json.dumps(persisted.parameters)
    assert all(secret not in encoded for secret in secrets)
    assert persisted.parameters["baseline"] == [
        {
            "source": "ha-01",
            "signature": "connection failed /stok=[redacted]/ds",
            "occurrences": count,
        }
        for count in (3, 5)
    ]
    claim = poll(service).job
    assert claim.job_id == created.job_id
    assert claim.parameters == persisted.parameters
    assert previous["sources"][0]["findings"][0]["signature"].endswith(
        f"{secrets[0]}/ds"
    )


@pytest.mark.parametrize("infra_healthy", [False, True])
@pytest.mark.parametrize("truncated_count", [None, 0, 99])
def test_partial_control_preserves_other_source_baselines_after_restart(
    cycle, tmp_path, infra_healthy, truncated_count
):
    service, jobs, _incidents, now = cycle
    service.log_analysis_enabled = True
    service.log_sources = ("infra-01", "zwave-01", "ha-01")

    def complete_control(sources, counts, *, failed=False, truncated=False):
        now[0] += timedelta(minutes=1)
        created = service.request_log_health_check(now=now[0], sources=sources)
        claim = jobs.claim(
            {"worker_id": "katsuyu-test", "supported_types": ["logs.health_check"]}
        ).job
        assert claim is not None
        assert claim.job_id == created.job_id
        result = {
            "status": "KO" if any(counts) else "OK",
            "analyzed_at": now[0].isoformat(),
            "window_started_at": created.parameters["window_started_at"],
            "window_ended_at": created.parameters["window_ended_at"],
            "new_anomaly_count": 0,
            "worsening_anomaly_count": 0,
            "sources": [
                {
                    "source": source,
                    "status": "KO" if count else "OK",
                    "fetched_bytes": 100,
                    "truncated": truncated,
                    "analyzed_lines": 10,
                    "findings": [
                        {
                            "source": source,
                            "signature": "connection timeout",
                            "summary": "Connection timeout",
                            "category": "timeout",
                            "severity": "warning",
                            "occurrences": count,
                            "trend": "stable",
                        }
                    ]
                    if count
                    else [],
                }
                for source, count in zip(sources, counts, strict=True)
            ],
        }
        completion = {
            "worker_id": "katsuyu-test",
            "attempt": claim.attempt,
            "status": "FAILED" if failed else "SUCCEEDED",
        }
        if failed:
            completion["error"] = {"code": "test.failed", "message": "test failure"}
        else:
            completion["result"] = result
        jobs.complete(str(created.job_id), completion)
        jobs.mark_completion_processed(str(created.job_id))
        return created

    complete_control(["infra-01", "zwave-01"], [3, 8])
    partial = complete_control(["infra-01"], [0 if infra_healthy else 4])
    assert {item["source"] for item in partial.parameters["baseline"]} == {"infra-01"}
    complete_control(["zwave-01"], [99], failed=True)
    if truncated_count is not None:
        complete_control(
            ["infra-01", "zwave-01", "ha-01"], [truncated_count] * 3, truncated=True
        )
    # Reuse existing persisted results; no migration or in-memory cache is needed.
    reopened = DistributedJobRepository(tmp_path / "jobs.db", clock=lambda: now[0])
    try:
        service.job_repository = reopened
        created = service.request_log_health_check(now=now[0])
        baseline = reopened.get(str(created.job_id)).parameters["baseline"]
        expected = {"zwave-01": 8}
        if not infra_healthy:
            expected["infra-01"] = 4
        assert {item["source"]: item["occurrences"] for item in baseline} == expected
        # A healthy empty result replaces its old findings; an unseen source has none.
        assert "ha-01" not in {item["source"] for item in baseline}
    finally:
        service.job_repository = jobs
        reopened.close()


@pytest.mark.parametrize("previous_hours", [2, 24])
@pytest.mark.parametrize("day", ["2026-09-20", "2026-10-25"])
def test_baseline_uses_latest_complete_matching_duration(
    cycle, tmp_path, previous_hours, day
):
    service, jobs, _incidents, now = cycle
    now[0] = datetime.fromisoformat(f"{day}T12:00:00").replace(
        tzinfo=ZoneInfo("Europe/Paris")
    )
    service.log_analysis_enabled = True
    service.log_sources = ("ha-01",)

    def complete(hours, count):
        now[0] += timedelta(minutes=1)
        job = service.request_log_health_check(now=now[0], window_hours=hours)
        claim = jobs.claim(
            {"worker_id": "katsuyu-test", "supported_types": ["logs.health_check"]}
        ).job
        assert claim.job_id == job.job_id
        jobs.complete(
            str(job.job_id),
            {
                "worker_id": "katsuyu-test",
                "attempt": claim.attempt,
                "status": "SUCCEEDED",
                "result": {
                    "status": "KO",
                    "analyzed_at": now[0].isoformat(),
                    "window_started_at": job.parameters["window_started_at"],
                    "window_ended_at": job.parameters["window_ended_at"],
                    "new_anomaly_count": 1,
                    "worsening_anomaly_count": 0,
                    "sources": [
                        {
                            "source": "ha-01",
                            "status": "KO",
                            "truncated": False,
                            "fetched_bytes": 100,
                            "analyzed_lines": count,
                            "findings": [
                                {
                                    "source": "ha-01",
                                    "signature": "error automation",
                                    "summary": "Automation error",
                                    "category": "automation",
                                    "severity": "error",
                                    "occurrences": count,
                                    "trend": "new",
                                }
                            ],
                        }
                    ],
                },
            },
        )
        jobs.mark_completion_processed(str(job.job_id))

    complete(previous_hours, 24)
    complete(2, 2)
    reopened = DistributedJobRepository(tmp_path / "jobs.db", clock=lambda: now[0])
    try:
        service.job_repository = reopened
        job = service.request_log_health_check(now=now[0], window_hours=24)
        baseline = reopened.get(str(job.job_id)).parameters["baseline"]
        assert [item["occurrences"] for item in baseline] == (
            [24] if previous_hours == 24 else []
        )
    finally:
        service.job_repository = jobs
        reopened.close()


def poll(service):
    return service.next_worker_job(
        {
            "worker_id": "katsuyu-test",
            "supported_types": ["logs.health_check", "ai.inference"],
        }
    )


def collect(cycle, *, changing=True, crash=False):
    service, jobs, _incidents, now = cycle
    window = {
        "window_started_at": (now[0] - timedelta(hours=24)).isoformat(),
        "window_ended_at": now[0].isoformat(),
    }
    job = jobs.create(
        {
            "job_id": str(uuid4()),
            "created_at": now[0].isoformat(),
            "type": "logs.health_check",
            "timeout": 900,
            "parameters": {**window, "sources": ["ha-01", "linky-01"]},
        }
    )
    claim = poll(service)
    assert claim.job.job_id == job.job_id
    assert not claim.job.shutdown_after_completion
    result = {
        **window,
        "status": "KO",
        "analyzed_at": now[0].isoformat(),
        "new_anomaly_count": 2 if changing else 0,
        "worsening_anomaly_count": 0,
        "sources": [
            {
                "source": source,
                "status": "KO",
                "fetched_bytes": 100,
                "truncated": False,
                "analyzed_lines": 2,
                "findings": [
                    {
                        "source": source,
                        "signature": f"timeout-{i}",
                        "summary": "Connection timeout",
                        "category": "timeout",
                        "severity": "error",
                        "occurrences": 2,
                        "reference_occurrences": 0
                        if changing and source == "ha-01"
                        else 2,
                        "trend": "new" if changing and source == "ha-01" else "stable",
                    }
                    for i in range(2)
                ],
            }
            for source in ["ha-01", "linky-01"]
        ],
    }
    completion = {
        "worker_id": "katsuyu-test",
        "attempt": claim.job.attempt,
        "status": "SUCCEEDED",
        "result": result,
    }
    if crash:
        jobs.complete(str(job.job_id), completion)
    else:
        service.complete_job(str(job.job_id), completion)
    return job, completion


@pytest.mark.parametrize("crash", [False, True])
def test_changed_logs_enqueue_only_required_ai_before_shutdown(cycle, crash):
    service, jobs, incidents, _now = cycle
    log_job, completion = collect(cycle, crash=crash)
    # A restart/recreated service sees the durable result, not an empty queue.
    if crash:
        service = AdministrationService(
            infrastructure_repository=service.infrastructure_repository,
            job_repository=jobs,
            incident_repository=incidents,
            expertise_service=service.expertise_service,
        )
    next_work = poll(service)
    assert not next_work.shutdown_requested
    assert next_work.job.type == "ai.inference"
    assert (
        incidents.get(next_work.job.parameters["incident_id"]).equipment_id == "ha-01"
    )
    linky = next(i for i in incidents.list() if i.equipment_id == "linky-01")
    assert linky.latest_decision["decision"] == "stable"
    assert not poll(service).shutdown_requested  # still running
    service.complete_job(str(log_job.job_id), completion)  # response retry
    assert jobs.count("ai.inference") == 1
    ai = next_work.job
    service.complete_job(
        str(ai.job_id),
        {
            "worker_id": "katsuyu-test",
            "attempt": ai.attempt,
            "status": "FAILED",
            "error": {"code": "ai.failed", "message": "test failure"},
        },
    )
    assert (
        incidents.get(ai.parameters["incident_id"]).latest_decision["cycle_status"]
        == "ai_failed"
    )
    assert poll(service).shutdown_requested
    assert not poll(service).shutdown_requested  # grant consumed


def test_stable_logs_refresh_without_ai(cycle):
    service, jobs, incidents, _now = cycle
    collect(cycle, changing=False)
    assert jobs.count("ai.inference") == 0
    assert all(i.latest_decision["decision"] == "stable" for i in incidents.list())
    assert poll(service).shutdown_requested


def test_timed_out_ai_records_failure_then_allows_shutdown(cycle):
    service, _jobs, incidents, now = cycle
    collect(cycle)
    ai = poll(service).job
    now[0] += timedelta(seconds=1800)
    assert poll(service).shutdown_requested
    assert (
        incidents.get(ai.parameters["incident_id"]).latest_decision["cycle_status"]
        == "ai_failed"
    )


def test_manual_worker_and_disabled_shutdown_are_preserved(cycle):
    service, jobs, _incidents, now = cycle
    service.wake_shutdown_after_completion = False
    assert not poll(service).shutdown_requested
    service.wake_shutdown_after_completion = True
    assert poll(service).shutdown_requested
    now[0] += timedelta(hours=1)
    jobs.register_worker(
        {
            "worker_id": "katsuyu-test",
            "platform": "Windows",
            "worker_version": "test",
            "capabilities": ["logs.health_check", "ai.inference"],
        }
    )
    assert not poll(service).shutdown_requested


def test_ai_success_is_recorded_once_and_covers_its_evidence(cycle):
    service, jobs, incidents, now = cycle
    collect(cycle)
    ai = poll(service).job
    completion = {
        "worker_id": "katsuyu-test",
        "attempt": ai.attempt,
        "status": "SUCCEEDED",
        "result": {
            "verdict": "OK",
            "generated_at": now[0].isoformat(),
            "model_id": "test",
            "model_sha256": "a" * 64,
            "summary": "Aucune intervention justifiée.",
            "metrics": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "ttft_ms": 1,
                "tokens_per_second": 1,
                "duration_seconds": 1,
            },
        },
    }
    service.complete_job(str(ai.job_id), completion)
    service.complete_job(str(ai.job_id), completion)
    incident = incidents.get(ai.parameters["incident_id"])
    assert incident_assessment(incident)["state"] == "watch"
    assert (
        sum(e.payload.get("cycle_status") == "ai_completed" for e in incident.events)
        == 1
    )
    assert not jobs.pending_completions()
    assert poll(service).shutdown_requested


def test_companion_summary_distinguishes_pending_authorizations_from_incidents(cycle):
    service, _jobs, _incidents, _now = cycle
    collect(cycle, changing=False)
    summary = service.read_companion_summary()
    assert summary["active_count"] == 2
    assert summary["pending_requests"] == 0
    assert summary["tsunade_message"] == "Aucune autorisation en attente"
    assert all(item["assessment"]["state"] == "watch" for item in summary["attention"])
    assert "Konoha : OK" not in str(service.read_companion_activity())


def test_next_worker_endpoint_requires_worker_authentication(cycle):
    service, _jobs, _incidents, _now = cycle
    server = AdministrationHTTPServer(
        service=service,
        token="admin-only",
        worker_token="worker-only",
        worker_only=True,
        port=0,
    )
    server.start()
    try:
        host, port = server.address
        payload = json.dumps(
            {
                "worker_id": "katsuyu-test",
                "supported_types": ["logs.health_check", "ai.inference"],
            }
        ).encode()
        url = f"http://{host}:{port}/v1/jobs/next"
        with pytest.raises(HTTPError) as error:
            urlopen(
                Request(
                    url, data=payload, headers={"Content-Type": "application/json"}
                ),
                timeout=2,
            )
        assert error.value.code == 401
        request = Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer worker-only",
            },
        )
        with urlopen(request, timeout=2) as response:
            result = json.load(response)
        assert result == {
            "protocol_version": 1,
            "job": None,
            "shutdown_requested": True,
        }
    finally:
        server.stop()
