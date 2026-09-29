"""Phase 4: explainable drifts from data Tsunade already receives."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ohana_agent.api.service import AdministrationService
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_status import ObservationStatus
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.preventive import TsunadePreventiveMonitor

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=PARIS)


def _host(
    at: datetime,
    *,
    disk: float | None = 40.0,
    uptime: int | None = 30 * 86_400,
    restarts: int | None = 0,
    node: str = "infra-01",
) -> Observation:
    return Observation(
        node=node,
        service="ohana-host",
        capability="host.health",
        status=ObservationStatus.HEALTHY,
        success=True,
        message="Host healthy",
        source="host-health",
        timestamp=at,
        metadata={
            "host_health": {
                "disk_percent": disk,
                "host_uptime_seconds": uptime,
                "agent_restarts": restarts,
            }
        },
    )


def _days(
    monitor: TsunadePreventiveMonitor,
    values: list[float],
    today: datetime = NOW,
) -> None:
    """One sample per day ending today, with a fixed boot long ago."""
    boot = today - timedelta(days=60)
    for offset, value in enumerate(values):
        at = today - timedelta(days=len(values) - 1 - offset)
        monitor.record_host_health(
            _host(at, disk=value, uptime=int((at - boot).total_seconds()))
        )


def _check(summary: dict, rule: str) -> dict:
    return next(check for check in summary["checks"] if check["id"] == rule)


def test_steady_disk_growth_toward_full_is_reported(tmp_path: Path) -> None:
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    _days(monitor, [70.0, 71.2, 72.1, 73.4, 74.5])

    summary = monitor.summary(now=NOW)

    assert summary["status"] == "watch"
    assert summary["headline"] == "Konoha est stable."
    [item] = summary["watch"]
    assert item["rule"] == "disk_growth"
    assert item["title"] == "INFRA-01 : espace disque en hausse depuis 5 jours"
    assert "70,0 % → 74,5 %" in item["detail"]
    assert item["evidence"]["rises"] == 4
    assert item["urgent"] is False
    assert summary["conclusion"] == "Aucune intervention nécessaire."
    assert "À surveiller :\n- INFRA-01 : espace disque" in summary["text"]


def test_slow_or_one_off_disk_changes_stay_normal(tmp_path: Path) -> None:
    slow = TsunadePreventiveMonitor(tmp_path / "slow.db")
    _days(slow, [60.0, 60.2, 60.4, 60.6, 60.8, 61.0, 61.2])
    jump = TsunadePreventiveMonitor(tmp_path / "jump.db")
    _days(jump, [60.0, 60.0, 68.0, 68.0, 68.0, 68.0])
    # Above 70 %, drifting slowly around one apt upgrade: still one jump.
    upgrade = TsunadePreventiveMonitor(tmp_path / "upgrade.db")
    _days(upgrade, [71.0, 71.1, 71.2, 74.5, 74.6, 74.6, 74.7])

    for monitor in (slow, jump, upgrade):
        summary = monitor.summary(now=NOW)
        assert summary["status"] == "stable"
        assert _check(summary, "disk_growth")["state"] == "ok"
        assert (
            summary["text"] == "Konoha est stable.\n\nAucune intervention nécessaire."
        )


def test_few_disk_days_are_insufficient_not_stable_by_guess(tmp_path: Path) -> None:
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    _days(monitor, [80.0, 85.0, 89.0])

    check = _check(monitor.summary(now=NOW), "disk_growth")

    assert check["state"] == "insufficient_data"
    assert check["nodes"][0]["days"] == 3


def test_disk_filling_within_a_week_asks_for_an_intervention(tmp_path: Path) -> None:
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    _days(monitor, [74.0, 76.0, 78.0, 80.0, 82.0])

    summary = monitor.summary(now=NOW)

    [item] = summary["watch"]
    assert item["urgent"] is True
    assert "90 % atteint dans environ 4 jours" in item["detail"]
    assert summary["conclusion"].startswith("Intervention à prévoir : INFRA-01")


def test_daily_aggregates_survive_a_restart_and_keep_the_day_maximum(
    tmp_path: Path,
) -> None:
    database = tmp_path / "control.db"
    first = TsunadePreventiveMonitor(database)
    first.record_host_health(_host(NOW - timedelta(hours=2), disk=50.0))
    first.record_host_health(_host(NOW - timedelta(hours=1), disk=55.0))
    first.close()

    second = TsunadePreventiveMonitor(database)
    second.record_host_health(_host(NOW, disk=52.0))
    second.flush()

    row = (
        sqlite3.connect(database)
        .execute(
            "SELECT minimum, maximum, last_value, samples FROM tsunade_trend_daily"
        )
        .fetchone()
    )
    assert row == (50.0, 55.0, 52.0, 3)


def test_host_boots_and_automatic_agent_restarts_are_counted_once(
    tmp_path: Path,
) -> None:
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    first_boot = NOW - timedelta(days=3)
    for minute in range(3):
        at = first_boot + timedelta(hours=1, minutes=minute)
        # /proc/uptime drifts by a second or two against the wall clock.
        monitor.record_host_health(
            _host(at, uptime=int((at - first_boot).total_seconds()) - minute)
        )
    summary = monitor.summary(now=NOW)
    assert _check(summary, "repeated_reboots")["state"] == "ok"

    second_boot = NOW - timedelta(days=1)
    at = second_boot + timedelta(minutes=5)
    monitor.record_host_health(
        _host(at, uptime=int((at - second_boot).total_seconds()), restarts=0)
    )
    monitor.record_host_health(_host(at + timedelta(hours=1), uptime=3900, restarts=1))

    summary = monitor.summary(now=NOW)
    [item] = summary["watch"]
    assert item["rule"] == "repeated_reboots"
    assert item["title"] == (
        "INFRA-01 : 2 démarrages et 1 redémarrage automatique de l'Agent en 7 jours"
    )


def test_a_lower_restart_counter_is_a_new_baseline_not_a_restart(
    tmp_path: Path,
) -> None:
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    boot = NOW - timedelta(days=30)
    for restarts in (4, 0, 0):
        monitor.record_host_health(
            _host(NOW, uptime=int((NOW - boot).total_seconds()), restarts=restarts)
        )

    check = _check(monitor.summary(now=NOW), "repeated_reboots")

    assert check["state"] == "ok"
    assert check["nodes"][0]["count"] == 0


def test_repeated_network_interruptions_come_from_incident_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "control.db"
    incidents = TsunadeIncidentRepository(database)
    for day, minutes in ((6, 4), (3, 12), (1, 2)):
        _network_incident(incidents, "esp-02", NOW - timedelta(days=day), minutes)
    _network_incident(incidents, "esp-02", NOW - timedelta(days=9), 5)
    _network_incident(incidents, "she-04", NOW - timedelta(days=2), 5)
    monitor = TsunadePreventiveMonitor(database)

    summary = monitor.summary(now=NOW)

    [item] = summary["watch"]
    assert item["title"] == "ESP-02 : 3 interruptions réseau en 7 jours"
    assert item["detail"] == "Dernière le 27/09 12:00, la plus longue 12 min."
    check = _check(summary, "network_interruptions")
    assert {n["node_id"]: n["count"] for n in check["nodes"]} == {
        "esp-02": 3,
        "she-04": 1,
    }
    repairs = (
        sqlite3.connect(database)
        .execute("SELECT COUNT(*) FROM tsunade_repairs")
        .fetchone()[0]
    )
    assert repairs == 0
    assert summary["automatic_actions"] is False


def test_active_incidents_replace_the_stable_headline(tmp_path: Path) -> None:
    database = tmp_path / "control.db"
    incidents = TsunadeIncidentRepository(database)
    _network_incident(incidents, "esp-02", NOW - timedelta(hours=1), None)

    summary = TsunadePreventiveMonitor(database).summary(now=NOW)

    assert summary["headline"] == "1 incident en cours, suivi par Tsunade."
    assert summary["status"] == "stable"


def test_malformed_host_health_never_disturbs_the_event_bus(tmp_path: Path) -> None:
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")

    class Event:
        observation = _host(NOW, disk=None, uptime=None, restarts=None)

    monitor.handle(Event())
    broken = _host(NOW)
    object.__setattr__(broken, "timestamp", "not a date")

    class Broken:
        observation = broken

    monitor.handle(Broken())

    assert monitor.summary(now=NOW)["status"] == "stable"


def _network_incident(
    incidents: TsunadeIncidentRepository,
    device: str,
    started: datetime,
    minutes: int | None,
) -> None:
    def observation(at: datetime, healthy: bool) -> Observation:
        return Observation(
            node="infra-01",
            service=device,
            capability="network.reachable",
            status=(
                ObservationStatus.HEALTHY if healthy else ObservationStatus.UNHEALTHY
            ),
            success=healthy,
            message="reachable" if healthy else "unreachable",
            source="network",
            timestamp=at,
            metadata={"target_type": "device", "device_id": device},
        )

    incidents.process(observation(started - timedelta(minutes=1), True))
    incidents.process(observation(started, False))
    if minutes is not None:
        incidents.process(observation(started + timedelta(minutes=minutes), True))


def test_agent_serves_the_detail_and_shizune_gets_only_the_essential(
    tmp_path: Path,
) -> None:
    database = tmp_path / "control.db"
    incidents = TsunadeIncidentRepository(database)
    monitor = TsunadePreventiveMonitor(database)
    # The service evaluates at the real current time.
    _days(monitor, [70.0, 71.2, 72.1, 73.4, 74.5], datetime.now(PARIS))
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infrastructure.yaml"
        ),
        incident_repository=incidents,
        preventive_monitor=monitor,
    )

    assert "preventive.read" in service.capabilities().operations
    detail = service.read_preventive_summary()
    assert [check["id"] for check in detail["checks"]] == [
        "disk_growth",
        "repeated_reboots",
        "network_interruptions",
        "memory_growth",
        "response_time",
        "log_errors_growth",
        "ha_unavailable_entities",
    ]
    essential = service.read_companion_summary()["preventive"]
    assert essential["status"] == "watch"
    assert essential["watch"] == [
        {
            "title": "INFRA-01 : espace disque en hausse depuis 5 jours",
            "urgent": False,
        }
    ]
    assert essential["conclusion"] == "Aucune intervention nécessaire."
    assert "evidence" not in str(essential)


def test_the_monitor_never_keeps_the_control_database_locked(tmp_path: Path) -> None:
    database = tmp_path / "control.db"
    monitor = TsunadePreventiveMonitor(database)
    monitor.record_host_health(_host(NOW))
    monitor.record_host_health(_host(NOW + timedelta(minutes=1), disk=41.0))
    monitor.summary(now=NOW + timedelta(minutes=2))

    other = sqlite3.connect(database, timeout=0)
    other.execute("BEGIN IMMEDIATE")
    other.rollback()
