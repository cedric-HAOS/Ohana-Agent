"""Replay unchanged new groups across incomplete collections and restarts."""

import copy
import json
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from tests.test_tsunade_followups import NoProbes, ai_result


def evidence():
    return {
        "sources": [
            {
                "source": "ha-01",
                "status": "KO",
                "truncated": True,
                "analyzed_lines": 5554,
                "findings": [
                    {
                        "source": "ha-01",
                        "signature": f"automation failure {name}",
                        "summary": "Automation failure",
                        "category": "automation",
                        "severity": "error",
                        "trend": "new",
                        "occurrences": 1,
                        "reference_occurrences": None,
                        "first_at": "2026-09-20T15:17:15+02:00" if name < 3 else None,
                        "last_at": "2026-09-20T15:17:15+02:00" if name < 3 else None,
                    }
                    for name in range(5)
                ],
            }
        ],
        "correlations": [],
        "window_started_at": "2026-09-19T16:41:00+02:00",
        "window_ended_at": "2026-09-20T16:41:00+02:00",
    }


def review(path, dispatched, result, *, available=True, operator=False):
    repository = TsunadeIncidentRepository(path)

    def dispatch(payload):
        dispatched.append(payload)
        return SimpleNamespace(job_id=payload["job_id"])

    expertise = TsunadeExpertiseService(
        incidents=repository,
        investigations=NoProbes(),
        ai_dispatcher=dispatch if available else None,
    )
    try:
        job = uuid4()
        incident_id = repository.record_log_health(job, result)[0]
        before = len(dispatched)
        expertise.review_log_health(incident_id, job, result)
        if len(dispatched) > before:
            expertise.record_ai_result(
                incident_id, dispatched[-1]["job_id"], ai_result()
            )
        expertise.review_log_health(incident_id, job, result)
        if operator:
            expertise.diagnose(
                incident_id, log_result=result["sources"][0], operator_requested=True
            )
        return repository.get(incident_id)
    finally:
        repository.close()


@pytest.mark.parametrize("legacy", [False, True])
def test_repeated_new_findings_do_not_restart_ai_after_reopen(tmp_path, legacy):
    path = tmp_path / "incidents.db"
    dispatched = []
    original = evidence()
    review(path, dispatched, original)
    assert len(dispatched) == 1
    if legacy:
        # Model the existing production history, before finding markers existed.
        with sqlite3.connect(path) as connection:
            for event_id, raw in connection.execute(
                "SELECT event_id,payload_json FROM tsunade_incident_events"
            ).fetchall():
                payload = json.loads(raw)
                payload.pop("reviewed_log_findings", None)
                connection.execute(
                    "UPDATE tsunade_incident_events SET payload_json=? "
                    "WHERE event_id=?",
                    (json.dumps(payload), event_id),
                )
    repeated = copy.deepcopy(original)
    repeated["window_ended_at"] = "2026-09-20T17:04:00+02:00"
    repeated["sources"][0]["findings"].reverse()
    for finding in repeated["sources"][0]["findings"]:
        finding["summary"] = "Reworded hypothesis"
        finding["first_at"] = None
        if finding["last_at"]:
            finding["last_at"] = "2026-09-20T13:17:15Z"
    incident = review(path, dispatched, repeated)
    assert len(dispatched) == 1
    assert incident.latest_decision["decision"] == "watch"
    assert "déjà" in incident.latest_decision["reason"]
    assert incident.state == "active"
    assert incident.context["truncated"] is True
    assert len(incident.context["findings"]) == 5
    assert original == evidence()
    review(path, dispatched, repeated, operator=True)
    assert len(dispatched) == 2


@pytest.mark.parametrize(
    "change", ["count", "date", "signature", "severity", "correlation"]
)
def test_material_new_evidence_remains_eligible(tmp_path, change):
    path = tmp_path / "incidents.db"
    dispatched = []
    result = evidence()
    review(path, dispatched, result)
    for finding in result["sources"][0]["findings"][:2]:
        if change == "count":
            finding["occurrences"] += 1
        elif change == "date":
            finding["last_at"] = "2026-09-20T17:00:00+02:00"
        elif change == "signature":
            finding["signature"] += " additional failure"
        elif change == "severity":
            finding["severity"] = "critical"
    if change == "correlation":
        result["correlations"] = [
            {
                "sources": ["ha-01", "infra-01"],
                "occurred_at": "2026-09-20T17:00:00+02:00",
                "summary": "Temporal proximity only",
            }
        ]
    review(path, dispatched, result)
    assert len(dispatched) == 2


def test_worker_unavailable_does_not_mark_findings_reviewed(tmp_path):
    path = tmp_path / "incidents.db"
    dispatched = []
    result = evidence()
    review(path, dispatched, result, available=False)
    assert dispatched == []
    review(path, dispatched, result)
    assert len(dispatched) == 1
    review(path, dispatched, result)
    assert len(dispatched) == 1


def test_unchanged_critical_finding_does_not_loop(tmp_path):
    path = tmp_path / "incidents.db"
    dispatched = []
    result = evidence()
    result["sources"][0]["findings"] = result["sources"][0]["findings"][:1]
    result["sources"][0]["findings"][0].update(severity="critical", trend="stable")
    review(path, dispatched, result)
    incident = review(path, dispatched, result)
    assert len(dispatched) == 1
    assert incident.latest_decision["decision"] == "watch"


def test_finding_markers_outlive_the_display_event_limit(tmp_path):
    path = tmp_path / "incidents.db"
    dispatched = []
    result = evidence()
    incident = review(path, dispatched, result)
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO tsunade_incident_events "
            "(incident_id,kind,occurred_at,summary,payload_json) VALUES (?,?,?,?,?)",
            [
                (
                    str(incident.incident_id),
                    "investigation",
                    "2026-09-20T17:00:00+02:00",
                    "Unrelated history",
                    "{}",
                )
            ]
            * 1001,
        )
    review(path, dispatched, result)
    assert len(dispatched) == 1


def test_interruption_after_queue_record_does_not_repeat_expertise(tmp_path):
    path = tmp_path / "incidents.db"
    dispatched = []
    result = evidence()
    review(path, dispatched, result)
    with sqlite3.connect(path) as connection:
        # The durable queue record and completion survived, but not the review end.
        connection.execute(
            "DELETE FROM tsunade_incident_events "
            "WHERE json_extract(payload_json, '$.review_job_id') IS NOT NULL"
        )
    review(path, dispatched, result)
    assert len(dispatched) == 1
