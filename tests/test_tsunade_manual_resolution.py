"""Phase 3: manual resolutions, Shikamaru verification and manual leads."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.local_time import paris_now
from ohana_agent.tsunade.repair_catalog import repair_spec

COMMAND = "sudo systemctl restart dnsmasq.service"


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


def _declared(
    repository: TsunadeIncidentRepository,
    description: str = COMMAND,
    *,
    opened_at: datetime | None = None,
):
    incident = repository.process(
        _observation(
            ObservationStatus.UNHEALTHY,
            opened_at or paris_now() - timedelta(seconds=5),
        )
    )
    assert incident is not None
    action = repository.declare_manual_resolution(
        incident.incident_id,
        {"description": description, "declared_by": "C", "source": "vision"},
    )
    return incident, action


def _confirm(repository: TsunadeIncidentRepository, incident_id):
    return repository.confirm_experience(
        incident_id, {"confirm": True, "source": "vision", "confirmed_by": "C"}
    )


def test_a_manual_action_confirmed_by_shikamaru_is_kept_only_on_request(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    try:
        incident, action = _declared(repository)
        assert action.status == "verifying"
        assert action.verification_deadline is not None

        repository.process(
            _observation(ObservationStatus.HEALTHY, paris_now() + timedelta(seconds=2))
        )
        resolved = repository.get(incident.incident_id)
        assert resolved.state == "resolved"
        assert resolved.manual_actions[0].status == "confirmed"
        assert "ne prouve pas" in resolved.manual_actions[0].result

        candidate = resolved.experience_candidate
        assert candidate is not None and candidate.kind == "manual"
        assert candidate.prompt.startswith(
            "Cette action semble avoir participé à la résolution."
        )
        assert "ne prouve pas à elle seule" in candidate.caution
        # Nothing is learned before the user's explicit confirmation.
        assert repository.list_experiences() == []

        experience = _confirm(repository, incident.incident_id)
        assert experience.action == {"kind": "manual", "description": COMMAND}
        assert (experience.attempt_count, experience.success_count) == (1, 1)
        assert repository.get(incident.incident_id).experience_candidate is None
    finally:
        repository.close()


def test_the_same_manual_action_confirmed_again_adds_to_its_history(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    try:
        for turn in range(2):
            # Each turn comes later: Tsunade ignores out-of-order observations.
            incident, _action = _declared(
                repository,
                "Redémarrer  la box   Freebox",
                opened_at=paris_now() + timedelta(seconds=10 * turn),
            )
            repository.process(
                _observation(
                    ObservationStatus.HEALTHY,
                    paris_now() + timedelta(seconds=10 * turn + 2),
                )
            )
            _confirm(repository, incident.incident_id)
        [experience] = repository.list_experiences()
        assert (experience.attempt_count, experience.success_count) == (2, 2)
    finally:
        repository.close()


def test_a_manual_action_not_followed_by_recovery_is_not_confirmed(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    try:
        incident, _action = _declared(repository)
        # Still degraded within the settle delay: no conclusion yet.
        repository.process(
            _observation(
                ObservationStatus.UNHEALTHY, paris_now() + timedelta(seconds=10)
            )
        )
        assert repository.get(incident.incident_id).manual_actions[0].status == (
            "verifying"
        )
        repository.process(
            _observation(
                ObservationStatus.UNHEALTHY, paris_now() + timedelta(seconds=120)
            )
        )
        assert repository.get(incident.incident_id).manual_actions[0].status == (
            "unconfirmed"
        )
        # A later recovery does not turn the declaration into a lead.
        repository.process(
            _observation(
                ObservationStatus.HEALTHY, paris_now() + timedelta(seconds=200)
            )
        )
        assert repository.get(incident.incident_id).experience_candidate is None
    finally:
        repository.close()


def test_a_manual_action_without_observation_expires_unconfirmed(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    try:
        incident, action = _declared(repository)
        with repository._connection:
            repository._connection.execute(
                "UPDATE tsunade_manual_actions SET verification_deadline=? "
                "WHERE action_id=?",
                (
                    (paris_now() - timedelta(seconds=1)).isoformat(),
                    str(action.action_id),
                ),
            )
        expired = repository.get(incident.incident_id).manual_actions[0]
        assert expired.status == "unconfirmed"
        assert "Aucune observation Shikamaru" in expired.result
    finally:
        repository.close()


def test_a_manual_lead_never_becomes_an_executable_repair(tmp_path: Path) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    try:
        incident, _action = _declared(repository)
        repository.process(
            _observation(ObservationStatus.HEALTHY, paris_now() + timedelta(seconds=2))
        )
        _confirm(repository, incident.incident_id)

        again = repository.process(
            _observation(
                ObservationStatus.UNHEALTHY, paris_now() + timedelta(seconds=5)
            )
        )
        repository.append_record(
            again.incident_id,
            {
                "kind": "diagnostic",
                "summary": "dnsmasq est arrêté.",
                "payload": {"epistemic_status": "confirmed_by_probe"},
            },
        )
        # Shown as a lead for the user...
        [lead] = repository.matching_experiences(repository.get(again.incident_id))
        [text] = TsunadeExpertiseService._experience_proposals([lead])
        assert "Ohana" in text and "jamais" in text and COMMAND in text
        # ...never as the known repair behind a catalogue proposal, and a
        # catalogue execution is not counted against it.
        repair = repository.propose_repair(
            again.incident_id, repair_spec("restart_service", "dnsmasq.service")
        )
        assert repair.known_repair is None
        repository.authorize_repair(
            again.incident_id,
            {"repair_id": str(repair.repair_id), "source": "vision"},
        )
        repository.mark_repair_executed(repair.repair_id)
        [experience] = repository.list_experiences()
        assert experience.attempt_count == 1
    finally:
        repository.close()


def test_manual_resolution_requires_an_active_incident_and_a_real_note(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    try:
        incident, _action = _declared(repository)
        with pytest.raises(ValueError, match="attend déjà"):
            repository.declare_manual_resolution(
                incident.incident_id, {"description": "Autre chose"}
            )
        with pytest.raises(ValidationError):
            repository.declare_manual_resolution(
                incident.incident_id, {"description": "ok"}
            )
        repository.process(
            _observation(ObservationStatus.HEALTHY, paris_now() + timedelta(seconds=2))
        )
        with pytest.raises(ValueError, match="incident actif"):
            repository.declare_manual_resolution(
                incident.incident_id, {"description": "Trop tard"}
            )
        with pytest.raises(LookupError):
            repository.declare_manual_resolution(uuid4(), {"description": "Inconnu"})
    finally:
        repository.close()
