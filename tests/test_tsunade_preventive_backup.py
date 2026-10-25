"""Phase 10: a backup is demonstrated restorable only by a declared restoration."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_status import ObservationStatus
from ohana_agent.tsunade.preventive import TsunadePreventiveMonitor

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=PARIS)


def _backup(node: str, at: datetime, *, healthy: bool = True) -> Observation:
    return Observation(
        node=node,
        service=node,
        capability="backup.run",
        status=ObservationStatus.HEALTHY if healthy else ObservationStatus.UNHEALTHY,
        success=healthy,
        message="Backup",
        source="backup",
        timestamp=at,
    )


def _rule(summary: dict) -> dict:
    return next(check for check in summary["checks"] if check["id"] == "backup_restore")


@pytest.fixture
def monitor(tmp_path: Path):
    instance = TsunadePreventiveMonitor(tmp_path / "control.db")
    yield instance
    instance.close()


def _states(monitor: TsunadePreventiveMonitor) -> dict[str, str]:
    return {
        entry["target"]: entry["state"] for entry in monitor.backup_posture(now=NOW)
    }


def test_without_any_backup_the_rule_has_nothing_to_judge(monitor) -> None:
    check = _rule(monitor.summary(now=NOW))

    assert check["state"] == "insufficient_data"
    assert check["items"] == [] if "items" in check else True


def test_a_backed_up_target_never_restored_is_explicitly_identified(monitor) -> None:
    monitor.record_observation(_backup("ha-01", NOW - timedelta(hours=10)))
    monitor.record_observation(_backup("infra-01", NOW - timedelta(hours=9)))

    summary = monitor.summary(now=NOW)

    assert _states(monitor) == {"ha-01": "never_tested", "infra-01": "never_tested"}
    titles = [item["title"] for item in summary["watch"]]
    assert "HA-01 : sauvegarde jamais testée en restauration" in titles
    assert _rule(summary)["state"] == "watch"
    assert summary["status"] == "watch"
    assert all(not item["urgent"] for item in summary["watch"])


def test_a_failed_backup_does_not_count_as_a_backup(monitor) -> None:
    monitor.record_observation(_backup("ha-01", NOW, healthy=False))

    assert monitor.backup_posture(now=NOW) == []


def test_a_successful_restoration_leaves_the_watch_list(monitor) -> None:
    monitor.record_observation(_backup("ha-01", NOW - timedelta(hours=10)))
    test = monitor.declare_restore_test(
        target="HA-01",
        outcome="ok",
        tested_at=NOW - timedelta(days=2),
        reference="Ohana-ha-01-20261018",
    )

    posture = monitor.backup_posture(now=NOW)[0]
    summary = monitor.summary(now=NOW)

    assert test["target"] == "ha-01"
    assert test["tested_at"].startswith("2026-10-18T12:00:00")
    assert posture["state"] == "verified"
    assert posture["last_verified_at"] == test["tested_at"]
    assert posture["last_backup_success_at"].startswith("2026-10-20T02:00:00")
    assert _rule(summary)["state"] == "ok"
    assert summary["watch"] == []


def test_a_failed_restoration_is_urgent_until_a_later_success(monitor) -> None:
    monitor.record_observation(_backup("infra-01", NOW - timedelta(hours=9)))
    monitor.declare_restore_test(
        target="infra-01",
        outcome="ok",
        tested_at=NOW - timedelta(days=30),
    )
    monitor.declare_restore_test(
        target="infra-01",
        outcome="failed",
        tested_at=NOW - timedelta(days=1),
        note="Clé age introuvable sur la machine de test.",
    )

    summary = monitor.summary(now=NOW)

    assert _states(monitor) == {"infra-01": "last_failed"}
    item = summary["watch"][0]
    assert item["urgent"] is True
    assert "Clé age introuvable" in item["detail"]
    assert summary["conclusion"].startswith("Intervention à prévoir")

    monitor.declare_restore_test(
        target="infra-01", outcome="ok", tested_at=NOW - timedelta(hours=1)
    )
    assert _states(monitor) == {"infra-01": "verified"}
    assert monitor.summary(now=NOW)["watch"] == []


def test_an_old_successful_restoration_becomes_stale(monitor) -> None:
    monitor.record_observation(_backup("ha-01", NOW - timedelta(hours=10)))
    monitor.declare_restore_test(
        target="ha-01", outcome="ok", tested_at=NOW - timedelta(days=181)
    )

    assert _states(monitor) == {"ha-01": "stale"}
    assert "181 jours" in monitor.backup_posture(now=NOW)[0]["text"]


def test_declarations_are_validated(monitor) -> None:
    with pytest.raises(ValueError, match="target"):
        monitor.declare_restore_test(target=" ", outcome="ok")
    with pytest.raises(ValueError, match="outcome"):
        monitor.declare_restore_test(target="ha-01", outcome="fine")
    with pytest.raises(ValueError, match="note"):
        monitor.declare_restore_test(target="ha-01", outcome="partial")
    with pytest.raises(ValueError, match="future"):
        monitor.declare_restore_test(
            target="ha-01",
            outcome="ok",
            tested_at=datetime.now(PARIS) + timedelta(days=1),
        )


def test_evidence_survives_a_restart(tmp_path: Path) -> None:
    first = TsunadePreventiveMonitor(tmp_path / "control.db")
    first.record_observation(_backup("ha-01", NOW))
    first.declare_restore_test(target="ha-01", outcome="ok", tested_at=NOW)
    first.close()

    second = TsunadePreventiveMonitor(tmp_path / "control.db")
    try:
        assert _states(second) == {"ha-01": "verified"}
    finally:
        second.close()


def test_service_exposes_and_records_restoration_tests(tmp_path: Path) -> None:
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
    try:
        operations = service.capabilities().operations
        assert "backups.restore_tests.read" in operations
        assert "backups.restore_tests.declare" in operations

        monitor.record_observation(_backup("zwave-01", NOW))
        declared = service.declare_restore_test(
            {
                "target": "zwave-01",
                "outcome": "ok",
                "tested_at": "2026-10-24T15:30:00",
                "reference": "essai sur machine de rechange",
            }
        )
        assert declared["tested_at"] == "2026-10-24T15:30:00+02:00"

        document = service.read_restore_tests()
        assert document["max_age_days"] == 180
        assert document["targets"][0]["target"] == "zwave-01"
        assert document["targets"][0]["history"][0]["reference"].startswith("essai")

        with pytest.raises(ValueError, match="ISO"):
            service.declare_restore_test(
                {"target": "zwave-01", "outcome": "ok", "tested_at": "hier"}
            )
    finally:
        monitor.close()


def test_service_starts_an_archive_check_on_request(tmp_path: Path) -> None:
    from ohana_agent.api.service import AdministrationService
    from ohana_agent.infrastructure.repository import (
        InfrastructureConfigurationRepository,
    )

    class Reporter:
        def __init__(self) -> None:
            self.requests: list[str | None] = []

        def request(self, target: str | None = None) -> list[str]:
            self.requests.append(target)
            return [target] if target else ["ha-01", "infra-01"]

    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infrastructure.yaml"
        ),
        preventive_monitor=monitor,
    )
    try:
        assert "backups.archives.verify" not in service.capabilities().operations
        with pytest.raises(LookupError):
            service.request_archive_check({})

        reporter = Reporter()
        service.archive_integrity = reporter
        assert "backups.archives.verify" in service.capabilities().operations
        assert service.request_archive_check({"target": " infra-01 "}) == {
            "started": ["infra-01"],
            "busy": False,
        }
        assert service.request_archive_check({})["started"] == ["ha-01", "infra-01"]
        assert reporter.requests == ["infra-01", None]
        with pytest.raises(ValueError, match="string"):
            service.request_archive_check({"target": 3})
    finally:
        monitor.close()
