"""Tsunade writes and returns Europe/Paris times only."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.incident_log_health import log_check_summary
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository

PARIS = ZoneInfo("Europe/Paris")
PARIS_SUMMER = timedelta(hours=2)


def _observation(at: datetime) -> Observation:
    return Observation(
        node="ha-01",
        service="mqtt",
        capability="mqtt.roundtrip",
        status=ObservationStatus.UNHEALTHY,
        success=False,
        message="[Errno 111] Connection refused",
        source="mqtt.roundtrip",
        id=uuid4(),
        timestamp=at,
        metadata={"device_id": "ha-01"},
    )


def test_every_incident_time_is_expressed_in_paris(tmp_path: Path) -> None:
    # Controlled Mosquitto repair: opening (UTC observation) and diagnosis
    # (recorded in Paris) used to show 12:51 and 14:52 in the same incident.
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    try:
        opened_at = datetime(2026, 9, 25, 12, 51, 56, tzinfo=UTC)
        incident = repository.process(_observation(opened_at))
        repository.append_record(
            incident.incident_id,
            {"kind": "diagnostic", "summary": "Diagnostic confirmé."},
        )

        details = repository.get(incident.incident_id)
        instants = [
            details.started_at,
            details.last_observed_at,
            *(event.occurred_at for event in details.events),
        ]
        # The diagnostic is stamped with the real clock, whose Paris offset
        # depends on the day the suite runs (summer or winter time).
        assert all(
            value.utcoffset() == value.astimezone(PARIS).utcoffset()
            for value in instants
        )
        assert details.started_at.utcoffset() == PARIS_SUMMER
        assert details.started_at == opened_at
        assert details.started_at.isoformat().startswith("2026-09-25T14:51:56")
        decided_at = datetime.fromisoformat(details.latest_decision["occurred_at"])
        assert decided_at.utcoffset() == decided_at.astimezone(PARIS).utcoffset()
        stored = repository._connection.execute(  # noqa: SLF001
            "SELECT started_at FROM tsunade_incidents"
        ).fetchone()[0]
        assert stored.endswith("+02:00")
    finally:
        repository.close()


def test_legacy_mixed_offsets_are_returned_in_paris_and_sorted_by_instant(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    try:
        incident = repository.process(
            _observation(datetime(2026, 9, 25, 12, 51, 56, tzinfo=UTC))
        )
        with repository._connection:  # noqa: SLF001 - rows written before the fix.
            for occurred_at, summary in (
                ("2026-09-25T14:52:00+02:00", "diagnostic, heure de Paris"),
                ("2026-09-25T12:54:11+00:00", "résolution, heure UTC"),
            ):
                repository._connection.execute(  # noqa: SLF001
                    """INSERT INTO tsunade_incident_events
                    (incident_id,kind,occurred_at,summary,payload_json)
                    VALUES (?,?,?,?,'{}')""",
                    (str(incident.incident_id), "result", occurred_at, summary),
                )

        events = repository.get(incident.incident_id).events
        assert all(event.occurred_at.utcoffset() == PARIS_SUMMER for event in events)
        activity = repository.companion_activity(limit=5)
        # As text, "12:54:11+00:00" sorted before "14:52:00+02:00".
        assert activity[0].title == "résolution, heure UTC"
        assert activity[0].occurred_at.isoformat() == "2026-09-25T14:54:11+02:00"
    finally:
        repository.close()


def test_log_check_summary_reports_findings_not_ko() -> None:
    source = {"source": "ha-01", "status": "KO", "truncated": False}
    assert log_check_summary(
        {"status": "KO", "sources": [{**source, "findings": [{}, {}, {}]}]}
    ) == ("Contrôle des journaux par Katsuyu terminé : 3 anomalie(s) regroupée(s)")
    assert (
        log_check_summary(
            {"status": "OK", "sources": [{**source, "status": "OK", "findings": []}]}
        )
        == "Contrôle des journaux par Katsuyu terminé : aucune anomalie"
    )
    assert log_check_summary(
        {"status": "OK", "sources": [{**source, "truncated": True, "findings": []}]}
    ).endswith("aucune anomalie, collecte incomplète")
    assert "KO" not in log_check_summary({})


def test_paris_differences_are_exact_across_the_autumn_clock_change() -> None:
    from ohana_agent.tsunade.local_time import paris_now, to_paris

    first_pass = to_paris(datetime(2026, 10, 25, 0, 30, tzinfo=UTC))  # 02:30 CEST
    second_pass = to_paris(datetime(2026, 10, 25, 1, 30, tzinfo=UTC))  # 02:30 CET

    assert first_pass.isoformat() == "2026-10-25T02:30:00+02:00"
    assert second_pass.isoformat() == "2026-10-25T02:30:00+01:00"
    # Same wall-clock time, one real hour apart.
    assert second_pass - first_pass == timedelta(hours=1)
    assert first_pass + timedelta(hours=1) == second_pass
    assert second_pass == datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    assert to_paris(datetime(2026, 10, 25, 1, 0, 2, tzinfo=UTC)) + timedelta(
        minutes=5
    ) > to_paris(datetime(2026, 10, 25, 1, 0, 2, tzinfo=UTC))
    assert paris_now().utcoffset() in {timedelta(hours=1), timedelta(hours=2)}


def test_paris_differences_are_exact_across_the_spring_clock_change() -> None:
    from ohana_agent.tsunade.local_time import to_paris

    before = to_paris(datetime(2027, 3, 28, 0, 59, tzinfo=UTC))  # 01:59 CET
    after = before + timedelta(minutes=2)

    assert before.isoformat() == "2027-03-28T01:59:00+01:00"
    assert after - before == timedelta(minutes=2)
    # The sum is the right instant; to_paris puts the right Paris label on it.
    assert to_paris(after).isoformat() == "2027-03-28T03:01:00+02:00"
