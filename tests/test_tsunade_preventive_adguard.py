"""A long AdGuard protection pause is reported, a short one is not."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_status import ObservationStatus
from ohana_agent.tsunade.preventive import TsunadePreventiveMonitor

PARIS = ZoneInfo("Europe/Paris")
START = datetime(2026, 10, 20, 8, 0, tzinfo=PARIS)


def _sync(at: datetime, *, enabled: bool, until: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        observation=Observation(
            node="infra-01",
            service="adguard-sync",
            capability="adguard_sync.status",
            status=ObservationStatus.HEALTHY,
            success=True,
            message="Sync",
            source="adguard_sync",
            timestamp=at,
            metadata={
                "protection": {"enabled": enabled, "disabled_until": until},
                "different_sections": [],
            },
        )
    )


def _rule(summary: dict) -> dict:
    return next(c for c in summary["checks"] if c["id"] == "adguard_protection")


@pytest.fixture
def monitor(tmp_path: Path):
    instance = TsunadePreventiveMonitor(tmp_path / "control.db")
    yield instance
    instance.close()


def _paused_for(monitor, hours: float, until: str | None = None) -> datetime:
    minutes = int(hours * 60)
    for minute in range(0, minutes + 1, 5):
        monitor.handle_observation(
            _sync(START + timedelta(minutes=minute), enabled=False, until=until)
        )
    return START + timedelta(minutes=minutes)


def test_active_protection_is_ok_and_not_reported(monitor) -> None:
    monitor.handle_observation(_sync(START, enabled=True))

    check = _rule(monitor.summary(now=START))

    assert check["state"] == "ok"
    assert monitor.summary(now=START)["watch"] == []


def test_a_short_pause_is_normal(monitor) -> None:
    now = _paused_for(monitor, 1.0, "2026-10-20T09:00:00+02:00")

    summary = monitor.summary(now=now)

    assert summary["watch"] == []
    assert "suspendue depuis 60 min" in _rule(summary)["nodes"][0]["summary"]


def test_a_pause_of_more_than_two_hours_is_reported_with_its_end(monitor) -> None:
    now = _paused_for(monitor, 3.0, "2026-10-21T08:00:00.123456789+02:00")

    summary = monitor.summary(now=now)

    item = summary["watch"][0]
    assert item["rule"] == "adguard_protection"
    assert item["title"] == "AdGuard : protection suspendue depuis 3 h 00"
    assert "jusqu'au 21/10 à 08:00" in item["detail"]
    assert item["urgent"] is False
    assert summary["conclusion"] == "Aucune intervention nécessaire."


def test_a_pause_without_end_says_so(monitor) -> None:
    now = _paused_for(monitor, 5.0, None)

    assert "sans fin prévue" in monitor.summary(now=now)["watch"][0]["detail"]


def test_resuming_the_protection_clears_the_alert(monitor) -> None:
    now = _paused_for(monitor, 3.0)
    assert monitor.summary(now=now)["watch"]

    monitor.handle_observation(_sync(now + timedelta(minutes=1), enabled=True))

    assert monitor.summary(now=now + timedelta(minutes=1))["watch"] == []


def test_a_pause_not_seen_for_a_long_time_is_not_evidence(monitor) -> None:
    now = _paused_for(monitor, 3.0)

    # The replication check stopped reporting: nothing proves the pause goes on.
    assert monitor.summary(now=now + timedelta(hours=2))["watch"] == []


def test_a_new_pause_after_a_gap_restarts_the_clock(monitor) -> None:
    _paused_for(monitor, 3.0)
    later = START + timedelta(hours=10)
    monitor.handle_observation(_sync(later, enabled=False))

    assert monitor.summary(now=later)["watch"] == []


def test_a_pause_survives_an_agent_restart(tmp_path: Path) -> None:
    first = TsunadePreventiveMonitor(tmp_path / "control.db")
    now = _paused_for(first, 3.0)
    first.close()

    second = TsunadePreventiveMonitor(tmp_path / "control.db")
    try:
        second.handle_observation(_sync(now + timedelta(minutes=2), enabled=False))
        item = second.summary(now=now + timedelta(minutes=2))["watch"][0]
        assert "3 h 02" in item["title"]
    finally:
        second.close()


def test_an_unreadable_setting_changes_nothing(monitor) -> None:
    _paused_for(monitor, 3.0)
    event = _sync(START + timedelta(hours=3, minutes=2), enabled=False)
    event.observation.metadata["protection"] = {"enabled": None}
    monitor.handle_observation(event)

    assert monitor.summary(now=START + timedelta(hours=3, minutes=2))["watch"]
