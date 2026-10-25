"""The Agent enters the restorations Ohana-Installer reports, once each."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.tsunade.preventive import TsunadePreventiveMonitor
from ohana_agent.tsunade.restore_reports import read_reports

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=PARIS)


def _report(directory: Path, name: str, **overrides: object) -> Path:
    document = {
        "schema_version": 1,
        "report_id": name,
        "target": "infra-01",
        "outcome": "ok",
        "mode": "icloud",
        "stage": "done",
        "backup_id": "20261024T020000Z",
        "detail": "Restauration terminée, services validés.",
        "finished_at": (NOW - timedelta(hours=3)).isoformat(),
        "installer_version": "1.16.0",
        **overrides,
    }
    path = directory / f"{name}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture
def reports(tmp_path: Path) -> Path:
    directory = tmp_path / "reports"
    directory.mkdir()
    return directory


@pytest.fixture
def monitor(tmp_path: Path, reports: Path):
    instance = TsunadePreventiveMonitor(
        tmp_path / "control.db", restore_report_directory=reports
    )
    yield instance
    instance.close()


def _infra(monitor: TsunadePreventiveMonitor, now: datetime = NOW) -> dict:
    return next(t for t in monitor.backup_posture(now=now) if t["target"] == "infra-01")


def test_a_reported_successful_restoration_verifies_infra_01(monitor, reports) -> None:
    _report(reports, "r1")

    posture = _infra(monitor)

    assert posture["state"] == "verified"
    assert posture["last_test"]["source"] == "installer"
    assert posture["last_test"]["reference"] == "20261024T020000Z"
    assert (
        "Rapport d'Ohana-Installer (icloud, étape terminée)"
        in (posture["last_test"]["note"])
    )


def test_a_failed_restoration_is_urgent_and_names_its_stage(monitor, reports) -> None:
    _report(
        reports,
        "r2",
        outcome="partial",
        stage="configuration",
        detail="Le service ohana-agent ne démarre pas.",
    )

    summary = monitor.summary(now=NOW)

    item = next(i for i in summary["watch"] if i["rule"] == "backup_restore")
    assert item["urgent"] is True
    assert "restauration des configurations" in item["detail"]
    assert "ne démarre pas" in item["detail"]
    assert _infra(monitor)["last_test"]["outcome"] == "partial"


def test_a_report_is_entered_only_once(monitor, reports) -> None:
    _report(reports, "r3")
    first = len(_infra(monitor)["history"])

    later = NOW + timedelta(minutes=5)
    assert len(_infra(monitor, later)["history"]) == first == 1


def test_a_later_user_declaration_still_counts(monitor, reports) -> None:
    _report(reports, "r4", outcome="failed", stage="download", detail="age: erreur")
    assert _infra(monitor)["state"] == "last_failed"

    monitor.declare_restore_test(target="infra-01", outcome="ok")

    posture = _infra(monitor, NOW + timedelta(minutes=2))
    assert posture["state"] == "verified"
    assert [t["source"] for t in posture["history"]] == ["user", "installer"]


def test_reports_are_read_at_most_once_a_minute(monitor, reports) -> None:
    assert monitor.backup_posture(now=NOW) == []
    _report(reports, "r5")

    assert monitor.backup_posture(now=NOW + timedelta(seconds=30)) == []
    assert monitor.backup_posture(now=NOW + timedelta(seconds=61))[0]["target"] == (
        "infra-01"
    )


def test_a_clock_ahead_of_the_agent_does_not_refuse_the_report(
    monitor, reports
) -> None:
    _report(reports, "r6", finished_at=(NOW + timedelta(hours=2)).isoformat())

    test = _infra(monitor)["last_test"]

    assert test["outcome"] == "ok"
    assert datetime.fromisoformat(test["tested_at"]) <= NOW


def test_broken_oversized_and_foreign_files_are_ignored(reports) -> None:
    (reports / "a.json").write_text("{not json", encoding="utf-8")
    (reports / "b.json").write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
    _report(reports, "c", outcome="fine")
    _report(reports, "d", finished_at="2026-10-25T10:00:00")  # no time zone
    (reports / "e.json").write_text(" " * 20_000, encoding="utf-8")
    (reports / "notes.txt").write_text("not a report", encoding="utf-8")
    _report(reports, "good")

    found = read_reports(reports)

    assert [report["report_id"] for report in found] == ["good"]


def test_without_a_directory_nothing_is_read(tmp_path: Path) -> None:
    monitor = TsunadePreventiveMonitor(tmp_path / "control.db")
    try:
        assert monitor.backup_posture(now=NOW) == []
    finally:
        monitor.close()
    assert read_reports(tmp_path / "does-not-exist") == []


def test_reports_survive_an_agent_restart_without_duplicates(
    tmp_path: Path, reports: Path
) -> None:
    _report(reports, "r7")
    first = TsunadePreventiveMonitor(
        tmp_path / "control.db", restore_report_directory=reports
    )
    assert len(_infra(first)["history"]) == 1
    first.close()

    second = TsunadePreventiveMonitor(
        tmp_path / "control.db", restore_report_directory=reports
    )
    try:
        assert len(_infra(second, NOW + timedelta(hours=1))["history"]) == 1
    finally:
        second.close()
