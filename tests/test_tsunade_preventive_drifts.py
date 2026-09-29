"""Phase 4 hardening: adaptive windows, seasonality, new trends, fewer alerts."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_status import ObservationStatus
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.preventive import TsunadePreventiveMonitor
from ohana_agent.tsunade.preventive_drifts import baseline_drift

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=PARIS)
TODAY = NOW.date()


def _points(values: list[float], today: date = TODAY) -> list[tuple[date, float]]:
    return [
        (today - timedelta(days=len(values) - 1 - index), value)
        for index, value in enumerate(values)
    ]


def test_a_steady_rise_over_its_own_baseline_is_a_drift() -> None:
    evaluation = baseline_drift(
        _points([50.0] * 14 + [62.0] * 7),
        today=TODAY,
        absolute_floor=5.0,
        relative_floor=0.1,
    )

    assert evaluation["state"] == "watch"
    assert evaluation["days_above"] == 7
    assert evaluation["baseline_days"] == 14


def test_a_noisy_metric_needs_a_larger_rise_adaptive_threshold() -> None:
    # The same +12 points is normal for a metric that already moves that much.
    noisy = [40.0, 60.0] * 7
    evaluation = baseline_drift(
        _points(noisy + [62.0] * 7),
        today=TODAY,
        absolute_floor=5.0,
        relative_floor=0.1,
    )

    assert evaluation["state"] == "ok"
    assert evaluation["threshold"] > 12


def test_two_high_days_are_not_a_trend() -> None:
    evaluation = baseline_drift(
        _points([50.0] * 14 + [50.0] * 5 + [70.0] * 2),
        today=TODAY,
        absolute_floor=5.0,
        relative_floor=0.1,
    )

    assert evaluation["state"] == "ok"


def test_weekly_seasonality_keeps_busy_weekends_normal() -> None:
    def usual(day: date) -> float:
        return 90.0 if day.weekday() >= 5 else 30.0

    points = [
        (TODAY - timedelta(days=offset), usual(TODAY - timedelta(days=offset)))
        for offset in range(34, -1, -1)
    ]
    evaluation = baseline_drift(
        points, today=TODAY, absolute_floor=5.0, relative_floor=0.1
    )

    assert evaluation["seasonal"] is True
    assert evaluation["state"] == "ok"


def test_too_little_history_is_insufficient_not_a_guess() -> None:
    evaluation = baseline_drift(
        _points([50.0] * 5 + [80.0] * 7),
        today=TODAY,
        absolute_floor=5.0,
        relative_floor=0.1,
    )

    assert evaluation["state"] == "insufficient_data"


def _host(at: datetime, **health: object) -> Observation:
    return Observation(
        node="infra-01",
        service="ohana-host",
        capability="host.health",
        status=ObservationStatus.HEALTHY,
        success=True,
        message="Host healthy",
        source="host-health",
        timestamp=at,
        metadata={"host_health": {"host_uptime_seconds": None, **health}},
    )


def _check(summary: dict, rule: str) -> dict:
    return next(check for check in summary["checks"] if check["id"] == rule)


def test_memory_rise_is_reported_with_its_evidence(tmp_path: Path) -> None:
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    for offset, value in enumerate([48.0] * 14 + [66.0] * 7):
        at = NOW - timedelta(days=20 - offset)
        monitor.record_host_health(_host(at, memory_percent=value, swap_percent=5.0))
    summary = monitor.summary(now=NOW)

    memory = _check(summary, "memory_growth")
    assert memory["state"] == "watch"
    [item] = [item for item in summary["watch"] if item["rule"] == "memory_growth"]
    assert item["title"] == "INFRA-01 : mémoire en hausse"
    assert "66" in item["detail"]
    assert item["subject"] == "infra-01:memory_percent"
    monitor.close()


def _latency(at: datetime, value: float, *, healthy: bool = True) -> Observation:
    return Observation(
        node="infra-01",
        service="dns-primary",
        capability="dns.resolve",
        status=ObservationStatus.HEALTHY if healthy else ObservationStatus.UNHEALTHY,
        success=healthy,
        message="DNS",
        source="dns",
        timestamp=at,
        latency_ms=value,
    )


def test_slower_dns_is_a_response_time_drift_failures_are_ignored(
    tmp_path: Path,
) -> None:
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    for offset in range(21):
        at = NOW - timedelta(days=20 - offset)
        value = 20.0 if offset < 14 else 90.0
        monitor.record_observation(_latency(at, value))
        monitor.record_observation(_latency(at + timedelta(hours=1), value))
        # A timeout is an incident, not a slower day.
        monitor.record_observation(_latency(at, 5000.0, healthy=False))
    summary = monitor.summary(now=NOW)

    [item] = [item for item in summary["watch"] if item["rule"] == "response_time"]
    assert item["title"] == "DNS dns-primary (INFRA-01) : temps de réponse en hausse"
    assert item["evidence"]["baseline_median"] == 20.0
    monitor.close()


def _log_check(connection: sqlite3.Connection, day: date, occurrences: int) -> None:
    findings = (
        [
            {
                "source": "ha-01",
                "signature": "<timestamp> error tapo camera timed out",
                "occurrences": occurrences,
            }
        ]
        if occurrences
        else []
    )
    connection.execute(
        """INSERT INTO distributed_jobs
        (job_id, type, status, finished_at, result_json) VALUES (?, ?, ?, ?, ?)""",
        (
            f"job-{day.isoformat()}",
            "logs.health_check",
            "SUCCEEDED",
            datetime(day.year, day.month, day.day, 4, 45, tzinfo=PARIS).isoformat(),
            json.dumps({"sources": [{"source": "ha-01", "findings": findings}]}),
        ),
    )


def test_log_anomaly_growing_over_daily_checks_is_reported(tmp_path: Path) -> None:
    database = tmp_path / "control.db"
    monitor = TsunadePreventiveMonitor(database)
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE distributed_jobs (job_id TEXT, type TEXT, status TEXT,
        finished_at TEXT, result_json TEXT)"""
    )
    connection.execute(
        """CREATE TABLE tsunade_accepted_log_signatures (source TEXT,
        signature TEXT, summary TEXT, accepted_at TEXT)"""
    )
    for offset in range(21):
        # Absent on several baseline days: those complete checks count as zero.
        occurrences = 0 if offset % 3 == 0 and offset < 14 else 10
        _log_check(connection, TODAY - timedelta(days=20 - offset), occurrences)
    for offset in range(7):
        connection.execute(
            "UPDATE distributed_jobs SET result_json=? WHERE job_id=?",
            (
                json.dumps(
                    {
                        "sources": [
                            {
                                "source": "ha-01",
                                "findings": [
                                    {
                                        "source": "ha-01",
                                        "signature": (
                                            "<timestamp> error tapo camera timed out"
                                        ),
                                        "occurrences": 200,
                                    }
                                ],
                            }
                        ]
                    }
                ),
                f"job-{(TODAY - timedelta(days=offset)).isoformat()}",
            ),
        )
    connection.commit()
    summary = monitor.summary(now=NOW)
    [item] = [item for item in summary["watch"] if item["rule"] == "log_errors_growth"]
    assert item["title"].startswith("HA-01 : « <timestamp> error tapo camera")

    # Accepted as known by the user: no longer a drift to watch.
    connection.execute(
        "INSERT INTO tsunade_accepted_log_signatures VALUES (?, ?, ?, ?)",
        ("ha-01", "<timestamp> error tapo camera timed out", "", NOW.isoformat()),
    )
    connection.commit()
    summary = monitor.summary(now=NOW)
    assert not [i for i in summary["watch"] if i["rule"] == "log_errors_growth"]
    connection.close()
    monitor.close()


def test_new_unavailable_home_assistant_entities_are_named(tmp_path: Path) -> None:
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    for offset in range(21):
        at = NOW - timedelta(days=20 - offset)
        recent = offset >= 14
        count = 12 if recent else 4
        # A Home Assistant restart makes everything unavailable for a minute.
        monitor.record_metric("ha-01", "ha_unavailable_entities", 900.0, at)
        monitor.record_metric("ha-01", "ha_unavailable_entities", float(count), at)
        entities = ["sensor.old"] + (
            ["sensor.tapo_c200", "light.salon"] if recent else []
        )
        monitor.record_snapshot(
            "ha-01", "ha_unavailable_snapshot", at, {"entities": entities}
        )
    summary = monitor.summary(now=NOW)

    [item] = [
        item for item in summary["watch"] if item["rule"] == "ha_unavailable_entities"
    ]
    assert item["evidence"]["newly_unavailable"] == ["light.salon", "sensor.tapo_c200"]
    assert "light.salon" in item["detail"]
    monitor.close()


def test_drifts_on_one_equipment_are_correlated_not_explained(tmp_path: Path) -> None:
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    for offset in range(21):
        at = NOW - timedelta(days=20 - offset)
        recent = offset >= 14
        monitor.record_host_health(_host(at, memory_percent=70.0 if recent else 40.0))
        monitor.record_observation(_latency(at, 90.0 if recent else 20.0))
    summary = monitor.summary(now=NOW)

    [correlation] = summary["correlations"]
    assert correlation["equipment_id"] == "infra-01"
    assert correlation["rules"] == ["memory_growth", "response_time"]
    assert "ne prouve aucune cause" in correlation["note"]
    memory = next(i for i in summary["watch"] if i["rule"] == "memory_growth")
    assert memory["correlated_with"] == [
        "DNS dns-primary (INFRA-01) : temps de réponse en hausse"
    ]
    monitor.close()


def test_muted_drift_leaves_the_watch_list_but_stays_visible(tmp_path: Path) -> None:
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    for offset, value in enumerate([48.0] * 14 + [66.0] * 7):
        at = NOW - timedelta(days=20 - offset)
        monitor.record_host_health(_host(at, memory_percent=value))
    monitor.mute("memory_growth", "infra-01:memory_percent", days=30, now=NOW)
    summary = monitor.summary(now=NOW)

    assert not [i for i in summary["watch"] if i["rule"] == "memory_growth"]
    [muted] = summary["muted"]
    assert muted["muted_until"].startswith("2026-10-29")
    assert summary["status"] == "stable"

    monitor.unmute("memory_growth", "infra-01:memory_percent")
    assert monitor.summary(now=NOW)["status"] == "watch"
    with pytest.raises(ValueError):
        monitor.mute("memory_growth", "infra-01", days=365)
    with pytest.raises(ValueError):
        monitor.mute("unknown", "infra-01", days=1)
    monitor.close()


def test_a_drift_an_open_incident_follows_is_not_a_new_alert(tmp_path: Path) -> None:
    database = tmp_path / "control.db"
    incidents = TsunadeIncidentRepository(database)
    monitor = TsunadePreventiveMonitor(database)
    for offset in range(21):
        at = NOW - timedelta(days=20 - offset)
        value = 20.0 if offset < 14 else 90.0
        monitor.record_observation(_latency(at, value))
    incidents.process(_latency(NOW, 5000.0, healthy=False))
    summary = monitor.summary(now=NOW)

    assert not [i for i in summary["watch"] if i["rule"] == "response_time"]
    [followed] = summary["followed_by_incident"]
    assert followed["rule"] == "response_time"
    incidents.close()
    monitor.close()


def test_availability_sampler_keeps_only_unavailable_identifiers(
    tmp_path: Path,
) -> None:
    from ohana_agent.tsunade.home_assistant_availability import (
        HomeAssistantAvailabilitySampler,
    )

    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    sampler = HomeAssistantAvailabilitySampler(
        url="http://ha.test:8123",
        token=lambda: "test-only",
        record_metric=monitor.record_metric,
        record_snapshot=monitor.record_snapshot,
        fetch=lambda: [
            {"entity_id": "sensor.a", "state": "unavailable", "attributes": {}},
            {"entity_id": "sensor.b", "state": "12.5"},
            {"entity_id": "light.c", "state": "unavailable"},
        ],
    )

    assert sampler.sample() == 2
    failing = HomeAssistantAvailabilitySampler(
        url="http://ha.test:8123",
        token=lambda: None,
        record_metric=monitor.record_metric,
        record_snapshot=monitor.record_snapshot,
    )
    assert failing.sample() is None
    monitor.flush()
    connection = sqlite3.connect(tmp_path / "control.db")
    detail = connection.execute(
        "SELECT detail_json FROM tsunade_trend_events "
        "WHERE kind = 'ha_unavailable_snapshot'"
    ).fetchone()[0]
    assert json.loads(detail) == {"count": 2, "entities": ["light.c", "sensor.a"]}
    connection.close()
    monitor.close()


def test_service_mutes_and_unmutes_a_drift(tmp_path: Path) -> None:
    from ohana_agent.api.service import AdministrationService
    from ohana_agent.infrastructure.repository import (
        InfrastructureConfigurationRepository,
    )

    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infrastructure.yaml"
        ),
        preventive_monitor=monitor,
    )

    assert "preventive.mute" in service.capabilities().operations
    muted = service.mute_preventive(
        {"rule": "network_interruptions", "subject": "she-04", "days": 7}
    )
    assert muted["muted_until"]
    assert service.unmute_preventive(
        {"rule": "network_interruptions", "subject": "she-04"}
    ) == {"rule": "network_interruptions", "subject": "she-04", "muted_until": None}
    with pytest.raises(ValueError):
        service.mute_preventive(
            {"rule": "network_interruptions", "subject": "x", "days": "7"}
        )
    monitor.close()
