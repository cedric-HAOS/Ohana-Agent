from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ohana_agent.api.service import AdministrationService
from ohana_agent.core.events import EventBus
from ohana_agent.runtime.administration_bootstrap import TsunadeObservationHandler
from ohana_agent.runtime.bootstrap import build_production_agent
from ohana_agent.tsunade.expertise import (
    TsunadeExpertiseService,
)
from ohana_agent.tsunade.incidents import (
    TsunadeIncidentRepository,
)


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
        if isinstance(handler, TsunadeObservationHandler):
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
        latest_decision=None,
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


@pytest.mark.parametrize("node_id", ["infra-01", "camera-01"])
def test_resolving_a_single_occurrence_incident_starts_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    node_id: str,
) -> None:
    # Mosquitto repair, 25 September: the MQTT incident had one failing
    # observation, so its resolution looked like a first occurrence and queued
    # a second logs.health_check for HA-01.
    resolved = SimpleNamespace(
        incident_id=uuid4(),
        state="resolved",
        severity="critical",
        occurrence_count=1,
        node_id=node_id,
        repairs=[],
        final_result="La capacité est revenue à un état sain.",
        message="MQTT round trip succeeded.",
        ended_at=datetime(2026, 9, 25, 14, 54, tzinfo=UTC),
        last_observed_at=datetime(2026, 9, 25, 14, 54, tzinfo=UTC),
        latest_decision=None,
    )

    handler, expertise_started, created_jobs, service = (
        _build_tsunade_observation_handler(tmp_path, monkeypatch, [resolved])
    )

    try:
        handler(SimpleNamespace(observation=object()))

        assert expertise_started == []
        assert created_jobs == []
    finally:
        _close_service(service)


def test_host_health_observations_reach_tsunade(tmp_path, monkeypatch) -> None:
    # host.health was exported to Vision only: an inactive ohana-vision.service
    # never opened a Tsunade incident (Phase 1 hardening).
    from ohana_agent.observation.events import HostHealthObserved

    subscriptions: list[tuple[type[Any], str]] = []
    original_subscribe = EventBus.subscribe

    def record(self: EventBus, event_type: type[Any], handler: Any) -> None:
        subscriptions.append((event_type, type(handler).__name__))
        original_subscribe(self, event_type, handler)

    monkeypatch.setattr(EventBus, "subscribe", record)
    _handler, _started, _jobs, service = _build_tsunade_observation_handler(
        tmp_path, monkeypatch, []
    )
    try:
        assert (HostHealthObserved, "TsunadeObservationHandler") in subscriptions
    finally:
        _close_service(service)
