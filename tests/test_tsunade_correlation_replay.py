"""Local replay of correlation dates observed on INFRA-01 on 2026-09-15."""

from types import SimpleNamespace
from uuid import uuid4

from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from tests.test_tsunade_followups import NoProbes, ai_result


def test_correlation_replay_survives_restart_and_preserves_new_information(tmp_path):
    path = tmp_path / "incidents.db"
    dispatched = []

    def dispatch(payload):
        dispatched.append(payload)
        return SimpleNamespace(job_id=payload["job_id"])

    def run(dates, expected_dispatches, *, available=True):
        # Reopen for every collection: the deduplication must be durable.
        repository = TsunadeIncidentRepository(path)
        expertise = TsunadeExpertiseService(
            incidents=repository,
            investigations=NoProbes(),
            ai_dispatcher=dispatch if available else None,
        )
        result = {
            "sources": [
                {
                    "source": "zwave-01",
                    "status": "KO",
                    "findings": [
                        {
                            "source": "zwave-01",
                            "signature": "client disconnected",
                            "summary": "Client disconnected",
                            "category": "network",
                            "severity": "warning",
                            "trend": "known",
                            "occurrences": 87,
                            "reference_occurrences": 86,
                        }
                    ],
                }
            ],
            "correlations": [
                {
                    "sources": ["infra-01", "zwave-01"],
                    "occurred_at": date,
                    "summary": "Temporal correlation (sanitized replay)",
                }
                for date in dates
            ],
        }
        try:
            job = uuid4()
            incident_id = repository.record_log_health(job, result)[0]
            before = len(dispatched)
            expertise.review_log_health(incident_id, job, result)
            assert len(dispatched) == expected_dispatches
            if len(dispatched) > before:
                expertise.record_ai_result(
                    incident_id, dispatched[-1]["job_id"], ai_result()
                )
            elif available:
                assert (
                    repository.get(incident_id).latest_decision["decision"] == "stable"
                )
            # A retried completion does not dispatch twice.
            expertise.review_log_health(incident_id, job, result)
            assert len(dispatched) == expected_dispatches
        finally:
            repository.close()

    dates = ["2026-09-15T18:23:05.518642Z", "2026-09-15T18:23:05.642184Z"]
    run(dates, 0, available=False)
    run(dates, 1)
    run(list(reversed(dates)), 1)
    run([*dates, "2026-09-15T19:23:05.518642Z"], 2)
