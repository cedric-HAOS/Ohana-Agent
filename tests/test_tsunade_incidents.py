"""Tests for Tsunade's persistent, deduplicated incident lifecycle."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from administration.incidents import TsunadeIncidentRepository
from observer import Observation, ObservationStatus


def _observation(
    status: ObservationStatus,
    observed_at: datetime,
    *,
    observation_id=None,
) -> Observation:
    return Observation(
        node="infra-01",
        service="dns",
        capability="dns.resolve",
        status=status,
        success=status is ObservationStatus.HEALTHY,
        message=f"DNS is {status.value}",
        source="dns.resolve",
        id=observation_id or uuid4(),
        timestamp=observed_at,
        metadata={"device_id": "infra-01", "server": "192.168.1.10"},
    )


def test_incident_is_deduplicated_escalated_resolved_and_recurrent(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    started = datetime(2026, 8, 24, 12, tzinfo=UTC)
    duplicate_id = uuid4()
    try:
        assert (
            repository.process(_observation(ObservationStatus.HEALTHY, started)) is None
        )
        opened = repository.process(
            _observation(
                ObservationStatus.DEGRADED,
                started + timedelta(minutes=1),
                observation_id=duplicate_id,
            )
        )
        assert opened is not None
        assert opened.severity == "degraded"
        assert opened.workflow_state == "new"
        assert opened.recurrence_count == 0
        assert opened.events[0].payload == {"from": "healthy", "to": "degraded"}
        assert (
            repository.process(
                _observation(
                    ObservationStatus.DEGRADED,
                    started + timedelta(minutes=1),
                    observation_id=duplicate_id,
                )
            )
            is None
        )

        escalated = repository.process(
            _observation(
                ObservationStatus.UNHEALTHY,
                started + timedelta(minutes=2),
            )
        )
        assert escalated is not None
        assert escalated.incident_id == opened.incident_id
        assert escalated.severity == "critical"
        assert escalated.occurrence_count == 2

        assert (
            repository.process(
                _observation(ObservationStatus.UNKNOWN, started + timedelta(minutes=3))
            )
            is None
        )
        assert len(repository.list(state="active")) == 1

        resolved = repository.process(
            _observation(ObservationStatus.HEALTHY, started + timedelta(minutes=4))
        )
        assert resolved is not None
        assert resolved.state == "resolved"
        assert resolved.workflow_state == "resolved"
        assert resolved.final_result == "Capability returned to healthy state."

        recurrent = repository.process(
            _observation(ObservationStatus.DEGRADED, started + timedelta(minutes=5))
        )
        assert recurrent is not None
        assert recurrent.incident_id != opened.incident_id
        assert recurrent.recurrence_count == 1
    finally:
        repository.close()


def test_incident_references_typed_records_and_observations(tmp_path: Path) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    try:
        incident = repository.process(
            _observation(
                ObservationStatus.UNHEALTHY,
                datetime(2026, 8, 24, 12, tzinfo=UTC),
            )
        )
        assert incident is not None
        recorded = repository.append_record(
            incident.incident_id,
            {
                "kind": "diagnostic",
                "summary": "DNS upstream unavailable",
                "payload": {"confidence": 1.0},
            },
        )
        assert [event.kind for event in recorded.events] == ["opened", "diagnostic"]
        assert recorded.events[0].observation_id == incident.last_observation_id
        assert recorded.context["server"] == "192.168.1.10"
        assert recorded.workflow_state == "in_progress"
    finally:
        repository.close()


def test_log_health_synthesis_opens_updates_and_resolves_one_incident(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    finding = {
        "source": "zwave-01",
        "signature": "node <value> transmission failed",
        "category": "zwave",
        "severity": "error",
        "summary": "Node 17 transmission failed",
        "occurrences": 38,
        "first_at": "2026-08-24T02:41:00+00:00",
        "last_at": "2026-08-24T17:52:00+00:00",
        "trend": "new",
    }
    try:
        repository.record_log_health(
            uuid4(),
            {
                "status": "KO",
                "sources": [
                    {
                        "source": "zwave-01",
                        "status": "KO",
                        "findings": [finding],
                    }
                ],
            },
        )
        active = repository.list(state="active")
        assert len(active) == 1
        assert active[0].capability_id == "logs.health"
        assert active[0].severity == "critical"

        repository.record_log_health(
            uuid4(),
            {
                "status": "OK",
                "sources": [{"source": "zwave-01", "status": "OK", "findings": []}],
            },
        )
        resolved = repository.list(state="resolved")
        assert len(resolved) == 1
        assert resolved[0].workflow_state == "resolved"
        assert "no significant anomaly" in (resolved[0].final_result or "")
    finally:
        repository.close()
