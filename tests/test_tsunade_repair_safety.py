"""Phase 2 invariants: no late authorization, no endless verification."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.incident_repairs import REPAIR_VERIFICATION_SECONDS
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


@pytest.fixture
def repository(tmp_path: Path):
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    yield repository
    repository.close()


def _proposed(repository: TsunadeIncidentRepository, started: datetime):
    incident = repository.process(_observation(ObservationStatus.UNHEALTHY, started))
    repair = repository.propose_repair(
        incident.incident_id, repair_spec("restart_service", "dnsmasq.service")
    )
    return incident, repair


def _authorize(repository, incident, repair):
    return repository.authorize_repair(
        incident.incident_id,
        {"repair_id": str(repair.repair_id), "source": "vision"},
    )


def test_resolved_incident_expires_its_proposal(repository) -> None:
    started = datetime.now(UTC)
    incident, repair = _proposed(repository, started)
    repository.process(
        _observation(ObservationStatus.HEALTHY, started + timedelta(seconds=5))
    )

    details = repository.get(incident.incident_id)
    assert details.repairs[0].status == "expired"
    assert "résolu avant toute autorisation" in details.repairs[0].result
    with pytest.raises(ValueError, match="expiré"):
        _authorize(repository, incident, repair)
    assert repository.get_repair(repair.repair_id).executed_at is None


def test_expired_authorization_request_cannot_be_authorized(repository) -> None:
    incident, repair = _proposed(repository, datetime.now(UTC))
    with repository._connection:  # noqa: SLF001 - simulate seven days later.
        repository._connection.execute(  # noqa: SLF001
            "UPDATE tsunade_user_requests SET expires_at=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )

    with pytest.raises(ValueError, match="expiré"):
        _authorize(repository, incident, repair)
    assert repository.get_repair(repair.repair_id).status == "expired"
    assert repository.list_user_requests().requests == []


def test_refused_repair_stays_refused(repository) -> None:
    incident, repair = _proposed(repository, datetime.now(UTC))
    repository.refuse_repair(
        incident.incident_id, repair.repair_id, source="vision", answered_by="test"
    )
    with pytest.raises(ValueError, match="n’attend plus"):
        _authorize(repository, incident, repair)
    assert repository.get_repair(repair.repair_id).status == "refused"


def test_unconfirmed_repair_ends_unverified_and_is_not_repeated(repository) -> None:
    started = datetime.now(UTC) - timedelta(hours=1)
    incident, repair = _proposed(repository, started)
    _authorize(repository, incident, repair)
    repository.mark_repair_executed(repair.repair_id)
    executed_at = datetime.now(UTC) - timedelta(seconds=REPAIR_VERIFICATION_SECONDS + 1)
    with repository._connection:  # noqa: SLF001 - no Shikamaru observation since.
        repository._connection.execute(  # noqa: SLF001
            "UPDATE tsunade_repairs SET executed_at=?, verification_deadline=?",
            (executed_at.isoformat(), datetime.now(UTC).isoformat()),
        )

    details = repository.get(incident.incident_id)
    assert details.state == "active"
    assert [item.status for item in details.repairs] == ["unverified"]
    assert "n’est pas répétée automatiquement" in details.repairs[0].result
    assert any(event.payload.get("status") == "unverified" for event in details.events)

    # A later healthy observation resolves the incident but cannot rewrite the
    # repair as a success: nothing verified it in time.
    repository.process(_observation(ObservationStatus.HEALTHY, datetime.now(UTC)))
    assert repository.get_repair(repair.repair_id).status == "unverified"


def _executed_after(repository, observations: list[datetime]):
    """Execute a repair after the given failing observation times."""
    incident = None
    for observed_at in observations:
        incident = repository.process(
            _observation(ObservationStatus.UNHEALTHY, observed_at)
        )
    repair = repository.propose_repair(
        incident.incident_id, repair_spec("restart_service", "dnsmasq.service")
    )
    _authorize(repository, incident, repair)
    executed = repository.mark_repair_executed(repair.repair_id)
    return (executed.verification_deadline - executed.executed_at).total_seconds()


@pytest.mark.parametrize(
    ("intervals", "expected"),
    [
        ([], REPAIR_VERIFICATION_SECONDS),  # unknown cadence
        ([120], 360),  # MQTT every 2 min: three intervals
        ([30], 300),  # bounded below
        ([3600], 1800),  # bounded above
    ],
)
def test_verification_deadline_follows_the_observed_cadence(
    repository, intervals, expected
) -> None:
    now = datetime.now(UTC)
    times = [now - timedelta(seconds=sum(intervals) + 5)]
    for interval in intervals:
        times.append(times[-1] + timedelta(seconds=interval))
    assert _executed_after(repository, times) == pytest.approx(expected, abs=1)


def test_repair_without_stored_deadline_keeps_the_fixed_delay(repository) -> None:
    started = datetime.now(UTC) - timedelta(hours=1)
    incident, repair = _proposed(repository, started)
    _authorize(repository, incident, repair)
    repository.mark_repair_executed(repair.repair_id)
    with repository._connection:  # noqa: SLF001 - row written by Agent 1.33.
        repository._connection.execute(  # noqa: SLF001
            "UPDATE tsunade_repairs SET verification_deadline=NULL, executed_at=?",
            (
                (
                    datetime.now(UTC)
                    - timedelta(seconds=REPAIR_VERIFICATION_SECONDS - 60)
                ).isoformat(),
            ),
        )
    assert repository.get(incident.incident_id).repairs[0].status == "verifying"
    with repository._connection:  # noqa: SLF001
        repository._connection.execute(  # noqa: SLF001
            "UPDATE tsunade_repairs SET executed_at=?",
            (
                (
                    datetime.now(UTC)
                    - timedelta(seconds=REPAIR_VERIFICATION_SECONDS + 1)
                ).isoformat(),
            ),
        )
    assert repository.get(incident.incident_id).repairs[0].status == "unverified"


def test_existing_database_gains_the_deadline_column(tmp_path: Path) -> None:
    import sqlite3

    database = tmp_path / "legacy.db"
    legacy = sqlite3.connect(database)
    legacy.execute(
        """CREATE TABLE tsunade_repairs (
        repair_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL,
        operation TEXT NOT NULL, target TEXT NOT NULL, risk TEXT NOT NULL,
        status TEXT NOT NULL, proposed_at TEXT NOT NULL, authorized_at TEXT,
        authorization_source TEXT, authorized_by TEXT, executed_at TEXT,
        verified_at TEXT, result TEXT)"""
    )
    legacy.execute(
        "INSERT INTO tsunade_repairs (repair_id,incident_id,operation,target,"
        "risk,status,proposed_at) VALUES ('11111111-1111-4111-8111-111111111111',"
        "'22222222-2222-4222-8222-222222222222','restart_service',"
        "'dnsmasq.service','low','refused','2026-09-20T10:00:00+02:00')"
    )
    legacy.commit()
    legacy.close()

    repository = TsunadeIncidentRepository(database)
    try:
        columns = {
            row[1]
            for row in repository._connection.execute(  # noqa: SLF001
                "PRAGMA table_info(tsunade_repairs)"
            )
        }
        assert "verification_deadline" in columns
        assert (
            repository.get_repair("11111111-1111-4111-8111-111111111111").status
            == "refused"
        )
    finally:
        repository.close()
