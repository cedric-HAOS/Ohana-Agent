"""Phase 3 hardening: finer incident comparison and history for Vision."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_status import ObservationStatus
from ohana_agent.tsunade.incident_similarity import compare, fingerprint
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository

PARIS = ZoneInfo("Europe/Paris")
START = datetime(2026, 9, 1, 8, 0, tzinfo=PARIS)


def _host(at: datetime, status: ObservationStatus, reasons: list[str]) -> Observation:
    return Observation(
        node="infra-01",
        service="ohana-host",
        capability="host.health",
        status=status,
        success=status is ObservationStatus.HEALTHY,
        message=", ".join(reasons) or "Host healthy",
        source="host-health",
        timestamp=at,
        metadata={
            "target_type": "device",
            "device_id": "infra-01",
            "host_health": {"reasons": reasons},
        },
    )


def _episode(
    repository: TsunadeIncidentRepository, day: int, reasons: list[str]
) -> str:
    at = START + timedelta(days=day)
    incident = repository.process(_host(at, ObservationStatus.UNHEALTHY, reasons))
    repository.process(_host(at + timedelta(minutes=5), ObservationStatus.HEALTHY, []))
    return str(incident.incident_id)


def _fp(reasons: list[str], equipment: str = "infra-01", message: str = "x") -> dict:
    return fingerprint(
        equipment_id=equipment,
        capability_id="host.health",
        service_id="ohana-host",
        message=message,
        context={"host_health": {"reasons": reasons}},
    )


def test_same_capability_with_other_reasons_is_another_failure_mode() -> None:
    comparison = compare(
        _fp(["vision_http_unavailable"]), _fp(["disk_critical"], message="y")
    )

    assert comparison["different_nature"] is True
    assert comparison["score"] < 0.5
    assert (
        "Raisons : vision_http_unavailable / disk_critical" in comparison["differences"]
    )


def test_same_reasons_on_the_same_equipment_are_alike() -> None:
    comparison = compare(
        _fp(["systemd_units_inactive", "vision_http_unavailable"], message="a 1"),
        _fp(["systemd_units_inactive", "vision_http_unavailable"], message="a 22"),
    )

    assert comparison["score"] == 1.0
    assert "Même message" in comparison["matched"]
    assert (
        "Mêmes raisons : systemd_units_inactive, vision_http_unavailable"
        in comparison["matched"]
    )


def test_history_filters_by_outcome_and_period(tmp_path: Path) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    vision = _episode(repository, 0, ["vision_http_unavailable"])
    _episode(repository, 5, ["disk_critical"])
    repaired = _episode(repository, 10, ["systemd_units_failed"])
    repository._connection.execute(
        """INSERT INTO tsunade_repairs (repair_id, incident_id, operation, target,
        risk, status, proposed_at, executed_at) VALUES (?, ?, 'restart_service',
        'dnsmasq', 'low', 'succeeded', ?, ?)""",
        (str(uuid4()), repaired, START.isoformat(), START.isoformat()),
    )
    repository._connection.commit()

    everything = repository.history({})
    assert [item["outcome"] for item in everything["incidents"]] == [
        "repaired",
        "resolved",
        "resolved",
    ]
    assert everything["facets"]["equipment_id"] == ["infra-01"]
    only_repaired = repository.history({"outcome": "repaired"})
    assert [i["incident_id"] for i in only_repaired["incidents"]] == [repaired]
    early = repository.history({"until": (START + timedelta(days=1)).isoformat()})
    assert [i["incident_id"] for i in early["incidents"]] == [vision]
    assert early["incidents"][0]["duration_seconds"] == 300
    with pytest.raises(ValueError):
        repository.history({"outcome": "maybe"})
    repository.close()


def test_equipment_sheet_counts_incidents_and_repairs(tmp_path: Path) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    first = _episode(repository, 0, ["disk_critical"])
    _episode(repository, 3, ["disk_critical"])
    for status in ("succeeded", "failed"):
        repository._connection.execute(
            """INSERT INTO tsunade_repairs (repair_id, incident_id, operation, target,
            risk, status, proposed_at, executed_at) VALUES (?, ?, 'restart_service',
            'chrony', 'low', ?, ?, ?)""",
            (str(uuid4()), first, status, START.isoformat(), START.isoformat()),
        )
    repository._connection.commit()

    sheet = repository.equipment_history("infra-01")

    assert sheet["incident_count"] == 2
    assert sheet["total_duration_seconds"] == 600
    assert sheet["repairs"] == {
        "executed": 2,
        "succeeded": 1,
        "failed": 1,
        "success_rate": 50.0,
    }
    assert sheet["by_capability"][0]["capability_id"] == "host.health"
    with pytest.raises(LookupError):
        repository.equipment_history("unknown")
    repository.close()


def test_similar_incidents_rank_by_evidence_not_time(tmp_path: Path) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    alike = _episode(repository, 0, ["vision_http_unavailable"])
    _episode(repository, 19, ["disk_critical"])
    current = repository.process(
        _host(
            START + timedelta(days=20),
            ObservationStatus.UNHEALTHY,
            ["vision_http_unavailable"],
        )
    )

    similar = repository.similar_incidents(current.incident_id)

    # The disk incident, closer in time, is another failure mode.
    assert [item["incident_id"] for item in similar["similar"]] == [alike]
    assert similar["similar"][0]["similarity"]["score"] == 1.0
    assert "pas une cause" in similar["note"]
    repository.close()


def test_timeline_lists_recent_incidents_and_repairs(tmp_path: Path) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    now = datetime.now(PARIS)
    incident = repository.process(
        _host(now - timedelta(days=2), ObservationStatus.UNHEALTHY, ["disk_critical"])
    )
    repository._connection.execute(
        """INSERT INTO tsunade_repairs (repair_id, incident_id, operation, target,
        risk, status, proposed_at, executed_at) VALUES (?, ?, 'restart_service',
        'chrony', 'low', 'failed', ?, ?)""",
        (
            str(uuid4()),
            str(incident.incident_id),
            now.isoformat(),
            (now - timedelta(days=1)).isoformat(),
        ),
    )
    repository._connection.commit()

    timeline = repository.timeline()

    assert [i["outcome"] for i in timeline["incidents"]] == ["ongoing"]
    assert timeline["incidents"][0]["repair_failed"] is True
    assert [r["status"] for r in timeline["repairs"]] == ["failed"]
    repository.close()


def test_known_repair_of_another_failure_mode_is_not_cited(tmp_path: Path) -> None:
    import json

    from ohana_agent.tsunade.repair_catalog import repair_spec

    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    incident = repository.process(
        _host(START, ObservationStatus.UNHEALTHY, ["systemd_units_failed"])
    )
    for reasons, signature in (
        (["disk_critical"], "other-nature"),
        (["systemd_units_failed"], "same-nature"),
    ):
        repository._connection.execute(
            """INSERT INTO tsunade_experiences (experience_id, signature,
            equipment_id, capability_id, symptoms_json, context_json,
            observations_json, anomalies_json, validated_diagnostic, action_json,
            result, occurrence_count, success_count, failure_count, last_used_at,
            confidence, confirmed_by, confirmation_source, incident_id,
            attempt_count, state)
            VALUES (?, ?, 'infra-01', 'host.health', '[]', ?, '[]', '[]', 'd',
            ?, 'ok', 1, 1, 0, ?, 1, 'user', 'vision', ?, 1, 'active')""",
            (
                str(uuid4()),
                signature,
                json.dumps({"host_health": {"reasons": reasons}}),
                json.dumps(
                    {"operation": "restart_service", "target": "dnsmasq.service"}
                ),
                (
                    START + timedelta(days=1 if signature == "other-nature" else 0)
                ).isoformat(),
                str(uuid4()),
            ),
        )
    repository._connection.commit()
    decided = incident.model_copy(
        update={"latest_decision": {"epistemic_status": "confirmed_by_probe"}}
    )
    spec = repair_spec("restart_service", "dnsmasq.service")

    # The most recent experience (disk) is another failure mode: the older
    # one of the same nature is cited instead.
    with repository._lock:
        match = repository._known_repair_match_locked(decided, spec)
    assert match is not None
    assert "Même nature : systemd_units_failed" in match.criteria
    repository._connection.execute(
        "DELETE FROM tsunade_experiences WHERE signature = 'same-nature'"
    )
    repository._connection.commit()
    with repository._lock:
        assert repository._known_repair_match_locked(decided, spec) is None
    repository.close()
