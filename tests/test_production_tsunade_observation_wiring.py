from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ohana_agent.api.service import AdministrationService
from ohana_agent.core.events import EventBus
from ohana_agent.runtime.bootstrap import build_production_agent
from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository


class FakeVisionClient:
    """Discard Vision exports during production wiring tests."""

    def send_observation(self, payload: dict[str, Any]) -> None:
        del payload

    def send_infrastructure(self, payload: dict[str, Any]) -> None:
        del payload


def _build_tsunade_observation_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    incidents: list[SimpleNamespace],
) -> tuple[
    Callable[[Any], None],
    list[str],
    list[dict[str, Any]],
    AdministrationService,
]:
    management_token = tmp_path / "management.token"
    worker_token = tmp_path / "katsuyu.token"
    jobs_database = tmp_path / "distributed-jobs.db"

    management_token.write_text("management-secret\n", encoding="utf-8")
    worker_token.write_text("worker-secret\n", encoding="utf-8")

    application_path = tmp_path / "shikamaru.yaml"
    application_path.write_text(
        f"""\
version: 1
agent:
  name: Shikamaru
  environment: test
vision:
  enabled: true
  observation_url: http://127.0.0.1:8000/api/observations
  infrastructure_url: http://127.0.0.1:8000/api/infrastructure
administration:
  enabled: true
  token_file: {management_token.as_posix()}
  jobs:
    enabled: true
    database_path: {jobs_database.as_posix()}
    worker_token_file: {worker_token.as_posix()}
    logs:
      enabled: true
      sources:
        - infra-01
  dhcp:
    enabled: false
""",
        encoding="utf-8",
    )

    captured_handlers: dict[str, Callable[[Any], None]] = {}
    original_subscribe = EventBus.subscribe

    def capture_subscribe(
        self: EventBus,
        event_type: type[Any],
        handler: Callable[[Any], None],
    ) -> None:
        if getattr(handler, "__name__", "") == "handle_tsunade_observation":
            captured_handlers["tsunade"] = handler
        original_subscribe(self, event_type, handler)

    monkeypatch.setattr(EventBus, "subscribe", capture_subscribe)

    incident_iterator = iter(incidents)

    def fake_process(
        self: TsunadeIncidentRepository,
        observation: object,
    ) -> SimpleNamespace:
        del self, observation
        return next(incident_iterator)

    monkeypatch.setattr(
        TsunadeIncidentRepository,
        "process",
        fake_process,
    )

    expertise_started: list[str] = []

    def fake_start(
        self: TsunadeExpertiseService,
        incident_id: object,
        *,
        log_result: dict[str, Any] | None = None,
    ) -> None:
        del self, log_result
        expertise_started.append(str(incident_id))

    monkeypatch.setattr(
        TsunadeExpertiseService,
        "start",
        fake_start,
    )

    created_jobs: list[dict[str, Any]] = []

    def fake_create_job(
        self: AdministrationService,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        del self
        created_jobs.append(payload)
        return payload

    monkeypatch.setattr(
        AdministrationService,
        "create_job",
        fake_create_job,
    )

    agent = build_production_agent(
        application_config_path=application_path,
        vision_client=FakeVisionClient(),
    )

    assert agent.administration_runtime is not None
    service = agent.administration_runtime.service

    assert "tsunade" in captured_handlers

    return (
        captured_handlers["tsunade"],
        expertise_started,
        created_jobs,
        service,
    )


def _close_service(service: AdministrationService) -> None:
    if service.job_repository is not None:
        service.job_repository.close()

    if service.incident_repository is not None:
        service.incident_repository.close()


def test_first_incident_without_log_source_starts_tsunade_expertise_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident_id = uuid4()

    first_occurrence = SimpleNamespace(
        incident_id=incident_id,
        state="active",
        severity="degraded",
        occurrence_count=1,
        node_id="camera-01",
    )
    repeated_occurrence = SimpleNamespace(
        incident_id=incident_id,
        state="active",
        severity="degraded",
        occurrence_count=2,
        node_id="camera-01",
    )

    handler, expertise_started, created_jobs, service = (
        _build_tsunade_observation_handler(
            tmp_path,
            monkeypatch,
            [first_occurrence, repeated_occurrence],
        )
    )

    try:
        handler(SimpleNamespace(observation=object()))
        handler(SimpleNamespace(observation=object()))

        assert expertise_started == [str(incident_id)]
        assert created_jobs == []
    finally:
        _close_service(service)


def test_first_incident_with_log_source_queues_logs_without_direct_expertise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident_id = uuid4()

    incident = SimpleNamespace(
        incident_id=incident_id,
        state="active",
        severity="degraded",
        occurrence_count=1,
        node_id="infra-01",
    )

    handler, expertise_started, created_jobs, service = (
        _build_tsunade_observation_handler(
            tmp_path,
            monkeypatch,
            [incident],
        )
    )

    try:
        handler(SimpleNamespace(observation=object()))

        assert expertise_started == []
        assert len(created_jobs) == 1

        job = created_jobs[0]

        assert job["type"] == "logs.health_check"
        assert job["parameters"]["sources"] == ["infra-01"]
        assert job["parameters"]["incident_id"] == str(incident_id)
    finally:
        _close_service(service)
