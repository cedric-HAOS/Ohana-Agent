"""Tests for attaching a downstream symptom to a declared upstream incident."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.runtime.administration_bootstrap import TsunadeObservationHandler
from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.incident_correlation import declared_dependencies
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.investigations import InvestigationResult

STARTED = datetime(2026, 9, 25, 9, 11, tzinfo=UTC)
TELEMETRY = "home_assistant.telemetry.freshness"


def _infrastructure(depends_on: object = ("mqtt",)) -> InfrastructureConfig:
    telemetry_metadata: dict[str, object] = {
        "primary_entity_id": "sensor.micro_inverter_roof_power"
    }
    if depends_on is not None:
        telemetry_metadata["depends_on"] = list(depends_on)
    return InfrastructureConfig.model_validate(
        {
            "infrastructure": {"id": "konoha", "name": "Konoha"},
            "nodes": [
                {
                    "id": node,
                    "name": node,
                    "endpoint": {"type": "host", "address": f"{node}.ohana.lan"},
                }
                for node in ("ha-01", "sun-01")
            ],
            "services": [
                {"id": "mqtt", "name": "Mosquitto", "type": "mqtt", "node": "ha-01"},
                {
                    "id": "sun-01-telemetry",
                    "name": "Micro-onduleur",
                    "type": "home_assistant_telemetry",
                    "node": "sun-01",
                    "metadata": telemetry_metadata,
                },
            ],
        }
    )


def _observation(
    *,
    node: str,
    service: str,
    capability: str,
    at: datetime,
    status: ObservationStatus = ObservationStatus.UNHEALTHY,
) -> Observation:
    return Observation(
        node=node,
        service=service,
        capability=capability,
        status=status,
        success=status is ObservationStatus.HEALTHY,
        message=f"{service} is {status.value}",
        source=capability,
        id=uuid4(),
        timestamp=at,
        metadata={"device_id": node},
    )


def _mqtt(repository, at=STARTED, status=ObservationStatus.UNHEALTHY):
    return repository.process(
        _observation(
            node="ha-01",
            service="mqtt",
            capability="mqtt.roundtrip",
            at=at,
            status=status,
        )
    )


def _telemetry_observation(seconds: int = 24) -> Observation:
    return _observation(
        node="sun-01",
        service="sun-01-telemetry",
        capability=TELEMETRY,
        at=STARTED + timedelta(seconds=seconds),
    )


class Investigations:
    def __init__(self, infrastructure: InfrastructureConfig) -> None:
        self.infrastructure_reader = lambda: infrastructure

    def execute(self, payload):
        return InvestigationResult(
            investigation_id=uuid4(),
            operation=payload["operation"],
            status="OK",
            started_at=STARTED,
            finished_at=STARTED,
            duration_seconds=0,
            result={},
        )


def _service(repository, infrastructure, dispatched):
    def dispatch(payload):
        dispatched.append(payload)
        return SimpleNamespace(job_id=uuid4())

    return TsunadeExpertiseService(
        incidents=repository,
        investigations=Investigations(infrastructure),  # type: ignore[arg-type]
        ai_dispatcher=dispatch,
    )


def test_declared_dependencies_are_explicit_bounded_and_deduplicated() -> None:
    assert declared_dependencies(_infrastructure(), "sun-01-telemetry") == ("mqtt",)
    assert declared_dependencies(_infrastructure(None), "sun-01-telemetry") == ()
    assert declared_dependencies(_infrastructure(), "unknown") == ()
    looping = _infrastructure(("mqtt", " mqtt ", "sun-01-telemetry", 3))
    assert declared_dependencies(looping, "sun-01-telemetry") == ("mqtt",)


def test_symptom_is_attached_to_active_upstream_without_ai(tmp_path: Path) -> None:
    # Controlled failure #3: the broker incident was open when sun-01 telemetry
    # went stale, yet the telemetry incident requested its own ai.inference.
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    dispatched: list[dict] = []
    try:
        upstream = _mqtt(repository)
        downstream = repository.process(_telemetry_observation())
        service = _service(repository, _infrastructure(), dispatched)

        outcome = service.diagnose(downstream.incident_id)

        assert outcome.status == "DETERMINISTIC"
        assert outcome.decision == "watch"
        assert dispatched == []
        decision = repository.get(downstream.incident_id).latest_decision
        assert decision["epistemic_status"] == "correlated_with_upstream"
        assert decision["diagnostic_level"] == "PROBABLE"
        assert decision["upstream_incident_id"] == str(upstream.incident_id)
        assert "mqtt (HA-01)" in decision["conclusion"]
        assert any(
            event.payload.get("downstream_incident_id") == str(downstream.incident_id)
            for event in repository.get(upstream.incident_id).events
        )
    finally:
        repository.close()


def test_undeclared_or_resolved_upstream_still_escalates(tmp_path: Path) -> None:
    dispatched: list[dict] = []
    repository = TsunadeIncidentRepository(tmp_path / "undeclared.db")
    try:
        _mqtt(repository)
        downstream = repository.process(_telemetry_observation())
        undeclared = _service(repository, _infrastructure(None), dispatched)
        assert undeclared.diagnose(downstream.incident_id).status == "AI_QUEUED"
    finally:
        repository.close()

    repository = TsunadeIncidentRepository(tmp_path / "resolved.db")
    try:
        _mqtt(repository)
        _mqtt(
            repository,
            at=STARTED + timedelta(seconds=10),
            status=ObservationStatus.HEALTHY,
        )
        downstream = repository.process(_telemetry_observation())
        declared = _service(repository, _infrastructure(), dispatched)
        assert declared.diagnose(downstream.incident_id).status == "AI_QUEUED"
    finally:
        repository.close()
    assert len(dispatched) == 2


def test_operator_request_is_not_absorbed_by_correlation(tmp_path: Path) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    try:
        _mqtt(repository)
        downstream = repository.process(_telemetry_observation())
        service = _service(repository, _infrastructure(), [])
        outcome = service.diagnose(downstream.incident_id, operator_requested=True)
        assert outcome.status == "AI_QUEUED"
    finally:
        repository.close()


def test_symptom_outliving_upstream_is_reevaluated(tmp_path: Path) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    started: list[str] = []
    handler = TsunadeObservationHandler(
        incidents=repository,
        expertise=SimpleNamespace(  # type: ignore[arg-type]
            start=lambda incident_id: started.append(str(incident_id))
        ),
        administration=SimpleNamespace(),  # type: ignore[arg-type]
        logs_config=SimpleNamespace(enabled=False, sources=[]),  # type: ignore[arg-type]
        notifications=None,
    )
    try:
        _mqtt(repository)
        downstream = repository.process(_telemetry_observation())
        _service(repository, _infrastructure(), []).diagnose(downstream.incident_id)

        handler(SimpleNamespace(observation=_telemetry_observation(300)))
        assert started == []  # Upstream still active: nothing new to examine.

        _mqtt(
            repository,
            at=STARTED + timedelta(seconds=360),
            status=ObservationStatus.HEALTHY,
        )
        handler(SimpleNamespace(observation=_telemetry_observation(600)))
        assert started == [str(downstream.incident_id)]
    finally:
        repository.close()
