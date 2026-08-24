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
        assert resolved.final_result == "La capacité est revenue à un état sain."

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
        "reference_occurrences": 3,
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
        assert active[0].context["findings"][0]["reference_occurrences"] == 3

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
        assert "aucune anomalie significative" in (resolved[0].final_result or "")
    finally:
        repository.close()


def test_repair_requires_authorization_and_experience_requires_confirmation(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    started = datetime.now(UTC)
    try:
        incident = repository.process(
            _observation(ObservationStatus.UNHEALTHY, started)
        )
        assert incident is not None
        repository.append_record(
            incident.incident_id,
            {
                "kind": "diagnostic",
                "summary": "dnsmasq est arrêté.",
                "payload": {"epistemic_status": "confirmed_by_probe"},
            },
        )
        repair = repository.propose_repair(
            incident.incident_id, {"operation": "restart_service"}
        )
        assert repair.status == "proposed"
        assert repair.authorized_at is None
        assert "résolution DNS" in repair.consequences[0]

        authorized = repository.authorize_repair(
            incident.incident_id,
            {
                "repair_id": str(repair.repair_id),
                "source": "vision",
                "authorized_by": "Cédric",
            },
        )
        assert authorized.authorization_source == "vision"
        repository.mark_repair_executed(repair.repair_id)
        resolved = repository.process(
            _observation(ObservationStatus.HEALTHY, started + timedelta(seconds=2))
        )
        assert resolved is not None
        details = repository.get(incident.incident_id)
        assert details.repairs[0].status == "succeeded"
        assert details.experience_candidate is not None
        assert repository.matching_experiences(details) == []

        experience = repository.confirm_experience(
            incident.incident_id,
            {"confirm": True, "source": "vision", "confirmed_by": "Cédric"},
        )
        assert experience.success_count == 1
        assert experience.validated_diagnostic == "dnsmasq est arrêté."
        assert experience.symptoms == ["DNS is unhealthy"]
        assert experience.context["server"] == "192.168.1.10"
        assert experience.observations[-1]["status"] == "healthy"
        assert repository.get(incident.incident_id).experience_candidate is None
        statistics = repository.statistics()
        assert statistics["incident_count"] == 1
        assert statistics["resolved_incident_count"] == 1
        assert statistics["learned_repair_count"] == 1
        assert statistics["repair_success_rate"] == 100.0
    finally:
        repository.close()
