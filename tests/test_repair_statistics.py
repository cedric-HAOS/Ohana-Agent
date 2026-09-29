"""Phase 3 hardening: detailed repair statistics and known repair ranking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.repair_catalog import repair_spec
from ohana_agent.tsunade.repair_ranking import (
    rank_key,
    reliability,
    wilson_lower_bound,
)


def test_one_success_is_not_better_than_nineteen_out_of_twenty() -> None:
    assert wilson_lower_bound(1, 1) < wilson_lower_bound(19, 20)
    assert wilson_lower_bound(0, 0) == 0.0
    assert wilson_lower_bound(20, 20) > 0.8


@pytest.mark.parametrize(
    ("success", "failure", "expected"),
    [
        (0, 0, "unproven"),
        (1, 1, "to_confirm"),
        (9, 1, "reliable"),
        (6, 3, "mixed"),
        (1, 3, "unreliable"),
    ],
)
def test_reliability_needs_verified_outcomes(success, failure, expected) -> None:
    assert reliability(success, failure) == expected


def test_a_recent_failure_makes_a_reliable_repair_unstable() -> None:
    assert (
        reliability(
            9,
            1,
            last_success_at="2026-09-20T10:00:00+02:00",
            last_failure_at="2026-09-28T10:00:00+02:00",
        )
        == "unstable"
    )


def test_ranking_puts_active_and_proven_repairs_first() -> None:
    proven = rank_key("active", 19, 1, "2026-09-20T10:00:00+02:00", None)
    lucky = rank_key("active", 1, 0, "2026-09-28T10:00:00+02:00", None)
    disabled = rank_key("disabled", 50, 0, "2026-09-28T10:00:00+02:00", None)
    assert sorted([disabled, lucky, proven]) == [proven, lucky, disabled]


def _observation(status: ObservationStatus, at: datetime) -> Observation:
    return Observation(
        node="infra-01",
        service="dns",
        capability="dns.resolve",
        status=status,
        success=status is ObservationStatus.HEALTHY,
        message=f"DNS is {status.value}",
        source="dns.resolve",
        id=uuid4(),
        timestamp=at,
        metadata={"device_id": "infra-01"},
    )


def _cycle(repository, start: datetime, *, succeeds: bool):
    incident = repository.process(_observation(ObservationStatus.UNHEALTHY, start))
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
    if succeeds:
        repository.mark_repair_executed(repair.repair_id)
        # Observation times only move forward, and follow the execution.
        repository.process(
            _observation(ObservationStatus.HEALTHY, start + timedelta(seconds=2))
        )
    else:
        repository.mark_repair_execution_failed(
            repair.repair_id, "chrony.service est masqué"
        )
    return incident


def test_statistics_separate_outcomes_and_name_failure_causes(tmp_path: Path) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    start = datetime.now(UTC)
    try:
        first = _cycle(repository, start, succeeds=True)
        repository.confirm_experience(
            first.incident_id,
            {"confirm": True, "source": "vision", "confirmed_by": "C"},
        )
        _cycle(repository, start + timedelta(hours=1), succeeds=False)
        _cycle(repository, start + timedelta(hours=2), succeeds=True)

        statistics = repository.repair_statistics()
        everything = statistics["periods"]["all"]
        assert everything["proposed"] == 3
        assert everything["succeeded"] == 2
        assert everything["failed"] == 1
        assert everything["success_rate"] == 66.7
        assert everything["reliable_rate"] < everything["success_rate"]
        assert everything["median_recovery_seconds"] is not None
        assert statistics["periods"]["7d"]["proposed"] == 3

        [repair] = statistics["by_repair"]
        assert (repair["operation"], repair["target"]) == (
            "restart_service",
            "dnsmasq.service",
        )
        assert repair["failure_causes"] == [
            {"cause": "chrony.service est masqué", "count": 1}
        ]
        assert repair["last_success_at"] and repair["last_failure_at"]
        [equipment] = statistics["by_equipment"]
        assert equipment["equipment_id"] == "infra-01"
    finally:
        repository.close()


def test_known_repairs_are_listed_best_first_with_their_reliability(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    start = datetime.now(UTC)
    try:
        incident = _cycle(repository, start, succeeds=True)
        repository.confirm_experience(
            incident.incident_id,
            {"confirm": True, "source": "vision", "confirmed_by": "C"},
        )
        [(experience, details)] = repository.ranked_experiences()
        assert details["rank"] == 1
        assert details["reliability"] == "to_confirm"
        assert details["success_rate"] == 100.0
        assert experience.state == "active"
    finally:
        repository.close()
