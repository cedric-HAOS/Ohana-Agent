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
            "UPDATE tsunade_repairs SET executed_at=?",
            (executed_at.isoformat(),),
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
