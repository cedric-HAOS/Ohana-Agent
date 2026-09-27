"""Phase 3: attempts, outcomes and lifecycle of known repairs."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.repair_catalog import repair_spec


def _observation(status: ObservationStatus, observed_at: datetime) -> Observation:
    return Observation(
        node="infra-01",
        service="dns",
        capability="dns.resolve",
        status=status,
        success=status is ObservationStatus.HEALTHY,
        message=f"DNS is {status.value}",
        source="dns.resolve",
        id=uuid4(),
        timestamp=observed_at,
        metadata={"device_id": "infra-01"},
    )


def _executed_repair(repository: TsunadeIncidentRepository, opened_at: datetime):
    incident = repository.process(_observation(ObservationStatus.UNHEALTHY, opened_at))
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
        incident.incident_id, repair_spec("restart_service", "dnsmasq.service")
    )
    repository.authorize_repair(
        incident.incident_id,
        {"repair_id": str(repair.repair_id), "source": "vision", "authorized_by": "C"},
    )
    return incident, repair


def _only_experience(repository: TsunadeIncidentRepository):
    experiences = repository.list_experiences()
    assert len(experiences) == 1
    return experiences[0]


def test_each_execution_of_a_known_repair_is_counted_with_its_outcome(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    start = datetime.now(UTC)
    try:
        incident, repair = _executed_repair(repository, start)
        repository.mark_repair_executed(repair.repair_id)
        repository.process(
            _observation(ObservationStatus.HEALTHY, start + timedelta(seconds=2))
        )
        saved = repository.confirm_experience(
            incident.incident_id,
            {"confirm": True, "source": "vision", "confirmed_by": "C"},
        )
        assert (saved.attempt_count, saved.success_count, saved.failure_count) == (
            1,
            1,
            0,
        )
        assert saved.last_success_at is not None
        assert saved.state == "active"

        # Same repair on a new incident: counted automatically, no second
        # save prompt for a repair Tsunade already knows.
        second, repair = _executed_repair(repository, start + timedelta(seconds=10))
        repository.mark_repair_executed(repair.repair_id)
        repository.process(
            _observation(ObservationStatus.HEALTHY, start + timedelta(seconds=12))
        )
        assert repository.get(second.incident_id).experience_candidate is None
        counted = _only_experience(repository)
        assert (counted.attempt_count, counted.success_count) == (2, 2)

        # A third execution that Shikamaru does not confirm is a failure.
        _, repair = _executed_repair(repository, start + timedelta(seconds=20))
        repository.mark_repair_executed(repair.repair_id)
        repository.process(
            _observation(ObservationStatus.UNHEALTHY, start + timedelta(seconds=300))
        )
        failed = _only_experience(repository)
        assert (failed.attempt_count, failed.success_count, failed.failure_count) == (
            3,
            2,
            1,
        )
        assert failed.last_failure_at is not None
    finally:
        repository.close()


def test_an_execution_error_counts_as_a_failed_attempt(tmp_path: Path) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    start = datetime.now(UTC)
    try:
        incident, repair = _executed_repair(repository, start)
        repository.mark_repair_executed(repair.repair_id)
        repository.process(
            _observation(ObservationStatus.HEALTHY, start + timedelta(seconds=2))
        )
        repository.confirm_experience(
            incident.incident_id,
            {"confirm": True, "source": "vision", "confirmed_by": "C"},
        )

        _, repair = _executed_repair(repository, start + timedelta(seconds=10))
        repository.mark_repair_execution_failed(
            repair.repair_id, "dnsmasq.service est masqué"
        )

        experience = _only_experience(repository)
        assert (experience.attempt_count, experience.failure_count) == (2, 1)
    finally:
        repository.close()


def test_a_disabled_known_repair_is_neither_offered_nor_counted(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    start = datetime.now(UTC)
    try:
        incident, repair = _executed_repair(repository, start)
        repository.mark_repair_executed(repair.repair_id)
        repository.process(
            _observation(ObservationStatus.HEALTHY, start + timedelta(seconds=2))
        )
        saved = repository.confirm_experience(
            incident.incident_id,
            {"confirm": True, "source": "vision", "confirmed_by": "C"},
        )

        disabled = repository.set_experience_state(
            saved.experience_id, {"state": "disabled", "reason": "Cible remplacée"}
        )
        assert disabled.state == "disabled"
        assert disabled.state_reason == "Cible remplacée"
        assert disabled.state_changed_at is not None
        assert repository.statistics()["learned_repair_count"] == 0

        second, repair = _executed_repair(repository, start + timedelta(seconds=10))
        assert repository.matching_experiences(repository.get(second.incident_id)) == []
        repository.mark_repair_executed(repair.repair_id)
        assert _only_experience(repository).attempt_count == 1

        obsolete = repository.set_experience_state(
            saved.experience_id, {"state": "obsolete"}
        )
        assert obsolete.state == "obsolete"
        reactivated = repository.set_experience_state(
            saved.experience_id, {"state": "active"}
        )
        assert reactivated.state == "active"
        assert reactivated.attempt_count == 1

        with pytest.raises(LookupError):
            repository.set_experience_state(uuid4(), {"state": "disabled"})
        with pytest.raises(ValidationError):
            repository.set_experience_state(saved.experience_id, {"state": "deleted"})
    finally:
        repository.close()


def test_experiences_saved_before_phase_3_gain_their_history(tmp_path: Path) -> None:
    path = tmp_path / "control.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE tsunade_experiences (
            experience_id TEXT PRIMARY KEY, signature TEXT NOT NULL UNIQUE,
            equipment_id TEXT NOT NULL, capability_id TEXT NOT NULL,
            symptoms_json TEXT NOT NULL, context_json TEXT NOT NULL,
            observations_json TEXT NOT NULL, anomalies_json TEXT NOT NULL,
            validated_diagnostic TEXT NOT NULL, action_json TEXT NOT NULL,
            result TEXT NOT NULL, occurrence_count INTEGER NOT NULL,
            success_count INTEGER NOT NULL, failure_count INTEGER NOT NULL,
            last_used_at TEXT NOT NULL, confidence REAL NOT NULL,
            confirmed_by TEXT NOT NULL, confirmation_source TEXT NOT NULL,
            incident_id TEXT NOT NULL)"""
    )
    connection.execute(
        """INSERT INTO tsunade_experiences VALUES
        (?,?,?,?,'[]','{}','[]','[]','dnsmasq arrêté',?,'Capacité saine',
        2,2,0,'2026-09-26T20:04:00+02:00',1,'C','vision',?)""",
        (
            str(uuid4()),
            "signature",
            "infra-01",
            "dhcp.status",
            '{"operation": "restart_service", "target": "dnsmasq.service"}',
            str(uuid4()),
        ),
    )
    connection.commit()
    connection.close()

    repository = TsunadeIncidentRepository(path)
    try:
        experience = _only_experience(repository)
        assert experience.attempt_count == 2
        assert experience.last_success_at == experience.last_used_at
        assert experience.last_failure_at is None
        assert experience.state == "active"
    finally:
        repository.close()
