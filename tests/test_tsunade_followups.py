"""Authorized collection, crash recovery and bounded second diagnosis."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.error import HTTPError
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.api.http import AdministrationHTTPServer
from ohana_agent.api.service import AdministrationService
from ohana_agent.companions.repository import CompanionRepository
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.jobs.repository import DistributedJobRepository
from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.incident_summary import incident_assessment
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from tests.test_shizune_companion import _companion_request, _pair


class NoProbes:
    def execute(self, payload):
        raise AssertionError("A follow-up must reuse its collected evidence")


def ai_result(*, incomplete=False):
    return {
        "verdict": "INSUFFICIENT_CONTEXT" if incomplete else "OK",
        "generated_at": datetime.now(ZoneInfo("Europe/Paris")).isoformat(),
        "model_id": "test",
        "model_sha256": "a" * 64,
        "summary": "Des journaux supplémentaires permettraient de vérifier la cause.",
        "missing_context": ["journaux ciblés"] if incomplete else [],
        "recommended_investigation": ["Collecter les journaux autour des timeouts."],
        "metrics": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "ttft_ms": 1,
            "tokens_per_second": 1,
            "duration_seconds": 1,
        },
    }


@pytest.fixture
def setup(tmp_path):
    jobs = DistributedJobRepository(tmp_path / "jobs.db")
    incidents = TsunadeIncidentRepository(tmp_path / "incidents.db")
    expertise = TsunadeExpertiseService(
        incidents=incidents, investigations=NoProbes(), ai_dispatcher=jobs.create
    )
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(
            tmp_path / "infra.yaml"
        ),
        job_repository=jobs,
        incident_repository=incidents,
        expertise_service=expertise,
        log_sources=("ha-01",),
    )
    incident = incidents.process(
        Observation(
            node="ha-01",
            service="logs",
            capability="logs.health",
            status=ObservationStatus.DEGRADED,
            success=False,
            message="Connection timeout",
            source="logs.health",
            timestamp=datetime.now(ZoneInfo("Europe/Paris")),
            metadata={
                "findings": [
                    {
                        "source": "ha-01",
                        "signature": "timeout",
                        "category": "timeout",
                        "occurrences": 2,
                        "summary": "Connection timeout",
                        "severity": "error",
                        "trend": "new",
                    }
                ]
            },
        )
    )
    jobs.register_worker(
        {
            "worker_id": "worker",
            "platform": "Windows",
            "worker_version": "test",
            "capabilities": ["ai.inference", "logs.investigate"],
        }
    )
    value = SimpleNamespace(
        service=service,
        jobs=jobs,
        incidents=incidents,
        incident=incident,
        expertise=expertise,
    )
    yield value
    jobs.close()
    incidents.close()


@pytest.mark.parametrize("truncated", [False, True, None, "false"])
def test_incomplete_review_uses_collection_facts_not_ai_truncation_claim(
    setup, truncated
):
    s = setup
    result = ai_result(incomplete=True)
    result["summary"] = "Les résultats sont tronqués, donc inutilisables."
    job_id = uuid4()
    evidence = [
        {
            "source": "investigation.followup",
            "content": json.dumps(
                {
                    "result": {
                        "matched_lines": 0,
                        "findings": [],
                        "truncated": truncated,
                    }
                }
            ),
        }
    ]
    s.expertise.record_ai_result(
        s.incident.incident_id, job_id, result, evidence=evidence
    )
    # A completion replay must keep the same deterministic explanation.
    s.expertise.record_ai_result(
        s.incident.incident_id, job_id, result, evidence=evidence
    )
    incident = s.incidents.get(s.incident.incident_id)
    records = [e for e in incident.events if e.kind == "diagnostic"]
    assert len(records) == 1
    diagnostic = records[0].payload
    assert diagnostic["decision"] == "watch"
    assert diagnostic["summary"] == result["summary"]
    assert diagnostic["epistemic_status"] == "hypothesis"
    assert "inutilisables" not in diagnostic["reason"]
    if type(truncated) is bool:
        assert diagnostic["collection_facts"]["truncated"] is truncated
        assert "0 lignes correspondantes, 0 anomalies reconnues" in diagnostic["reason"]
        assert (
            "Collecte tronquée." if truncated else "Collecte non tronquée."
        ) in diagnostic["reason"]
    else:
        assert diagnostic["collection_facts"] is None
        assert "tronquée" not in diagnostic["reason"]


def test_review_redacts_camera_session_from_previously_persisted_findings(setup):
    s = setup
    secret = "legacy.private*Token!"
    incident = s.incidents.get(s.incident.incident_id)
    incident.context["findings"][0]["summary"] = f"failed /stok={secret}/ds"
    incident.context["findings"][0]["references"] = [
        f"/stok={secret}/ds",
        "sensor.camera",
    ]
    collection = SimpleNamespace(
        job_id=uuid4(),
        parameters={"pattern": "timeout"},
        result={"matched_lines": 0, "findings": [], "truncated": False},
    )
    review = s.expertise.prepare_followup_review(incident, str(uuid4()), collection)
    encoded = json.dumps(review)
    assert secret not in encoded
    assert "/stok=[redacted]/ds" in encoded
    assert "sensor.camera" in encoded
    assert secret in incident.context["findings"][0]["summary"]


def poll(s):
    return s.service.next_worker_job(
        {"worker_id": "worker", "supported_types": ["ai.inference", "logs.investigate"]}
    ).job


def propose(s, *, crash=False):
    job = s.jobs.create(
        {
            "job_id": str(uuid4()),
            "created_at": datetime.now(ZoneInfo("Europe/Paris")).isoformat(),
            "type": "ai.inference",
            "timeout": 900,
            "parameters": {
                "incident_id": str(s.incident.incident_id),
                "question": "Pourquoi ?",
                "evidence": [
                    {
                        "source": "shikamaru.observation",
                        "content": json.dumps(
                            {
                                "last_observed_at": (
                                    s.incident.last_observed_at.isoformat()
                                )
                            }
                        ),
                    }
                ],
            },
        }
    )
    claimed = poll(s)
    assert claimed.job_id == job.job_id
    complete = {
        "worker_id": "worker",
        "attempt": claimed.attempt,
        "status": "SUCCEEDED",
        "result": ai_result(incomplete=True),
    }
    if crash:
        s.jobs.complete(str(job.job_id), complete)
    else:
        s.service.complete_job(str(job.job_id), complete)
    return job


def request(s):
    return s.service.read_companion_requests().requests[0]


def authorize(s):
    req = request(s)
    s.service.respond_companion_request(
        str(req.request_id), "iphone-test", {"choice": "AUTHORIZE"}
    )
    return req


def collected(s, *, matches=1, crash=False):
    job = poll(s)
    assert job.type == "logs.investigate"
    payload = {
        "worker_id": "worker",
        "attempt": job.attempt,
        "status": "SUCCEEDED",
        "result": {
            "status": "KO" if matches else "OK",
            "analyzed_at": datetime.now(ZoneInfo("Europe/Paris")).isoformat(),
            "source": "ha-01",
            "pattern": "timeout",
            "matched_lines": matches,
            "findings": [],
            "truncated": True,
        },
    }
    if crash:
        s.jobs.complete(str(job.job_id), payload)
    else:
        s.service.complete_job(str(job.job_id), payload)
    return job, payload


@pytest.mark.parametrize(
    "matches,anomalies,truncated", [(0, 0, False), (58, 0, False), (1, 1, True)]
)
def test_review_keeps_original_findings_separate_from_targeted_search(
    setup, matches, anomalies, truncated
):
    s = setup
    propose(s)
    authorize(s)
    job = poll(s)
    findings = (
        [
            {
                "source": "ha-01",
                "signature": "timeout",
                "category": "timeout",
                "severity": "error",
                "summary": "New connection timeout",
                "occurrences": 1,
                "trend": "new",
            }
        ]
        if anomalies
        else []
    )
    result = {
        "status": "KO" if anomalies else "OK",
        "analyzed_at": datetime.now(ZoneInfo("Europe/Paris")).isoformat(),
        "source": "ha-01",
        "pattern": "timeout",
        "matched_lines": matches,
        "findings": findings,
        "truncated": truncated,
    }
    s.service.complete_job(
        str(job.job_id),
        {
            "worker_id": "worker",
            "attempt": job.attempt,
            "status": "SUCCEEDED",
            "result": result,
        },
    )
    review = poll(s)
    evidence = {
        item["source"]: json.loads(item["content"])
        for item in review.parameters["evidence"]
    }
    original = evidence["logs.analysis"]["findings"]
    assert original[0]["summary"] == "Connection timeout"
    assert original[0]["occurrences"] == 2
    targeted = evidence["investigation.followup"]
    assert targeted["result"]["status"] == result["status"]
    assert targeted["result"]["matched_lines"] == matches
    assert targeted["result"]["truncated"] == truncated
    assert len(targeted["result"]["findings"]) == anomalies
    if anomalies:
        assert targeted["result"]["findings"][0]["summary"] == "New connection timeout"
    assert targeted["scope"] == job.parameters
    assert evidence["shikamaru.observation"]["last_observed_at"]
    assert "pas les anomalies" in review.parameters["question"]
    assert (
        "ne démontrent pas leur persistance actuelle" in review.parameters["question"]
    )


@pytest.mark.parametrize("matches", [0, 1])
@pytest.mark.parametrize("crash", [False, True])
def test_authorized_collection_is_reviewed_once_and_does_not_loop(
    setup, matches, crash
):
    s = setup
    propose(s, crash=crash)
    if crash:
        assert poll(s) is None  # recover AI result; no collection before consent
    req = request(s)
    assert req.kind == "investigation_authorization"
    assert req.created_at.tzinfo is not None
    assert "deux heures" in req.question
    assert s.jobs.count("logs.investigate") == 0
    assert (
        incident_assessment(s.incidents.get(s.incident.incident_id))["next_action"]
        == "decisions"
    )
    authorize(s)
    authorize_retry = s.service.respond_companion_request(
        str(req.request_id), "iphone-test", {"choice": "AUTHORIZE"}
    )
    assert authorize_retry.answer == "AUTHORIZE"
    assert s.jobs.count("logs.investigate") == 1
    job, completion = collected(s, matches=matches, crash=crash)
    review = poll(s)
    assert review.type == "ai.inference"
    evidence = next(
        e
        for e in review.parameters["evidence"]
        if e["source"] == "investigation.followup"
    )
    evidence = json.loads(evidence["content"])
    assert evidence["result"]["matched_lines"] == matches
    assert evidence["result"]["truncated"] is True
    assert evidence["scope"]["pattern"] == "timeout"
    s.service.complete_job(str(job.job_id), completion)
    assert s.jobs.count("ai.inference") == 2
    result = {
        "worker_id": "worker",
        "attempt": review.attempt,
        "status": "SUCCEEDED",
        "result": ai_result(incomplete=True),
    }
    s.service.complete_job(str(review.job_id), result)
    s.service.complete_job(str(review.job_id), result)
    assert poll(s) is None
    assert s.service.read_companion_requests().requests == []
    assert s.incidents.get_followup(str(req.request_id))["status"] == "incomplete"
    assert s.jobs.count("logs.investigate") == 1
    incident = s.incidents.get(s.incident.incident_id)
    assert incident.state == "active"
    assessment = incident_assessment(incident)
    assert assessment["state"] == "investigation_exhausted"
    assert assessment["next_action"] == "details"
    assert "Aucune nouvelle collecte" in assessment["followup"]["detail"]
    with pytest.raises(ValueError, match="déjà été réévaluée"):
        s.service.diagnose_incident(str(incident.incident_id))
    assert s.jobs.count("ai.inference") == 2
    assert (
        sum(
            e.payload.get("job_id") == str(job.job_id) and "result" in e.payload
            for e in incident.events
        )
        == 1
    )


@pytest.mark.parametrize("choice", ["REFUSE", "LATER"])
def test_refusal_or_deferral_never_executes(setup, choice):
    propose(setup)
    req = request(setup)
    answer = setup.service.respond_companion_request(
        str(req.request_id), "iphone", {"choice": choice}
    )
    assert answer.state == ("pending" if choice == "LATER" else "answered")
    assert setup.jobs.count("logs.investigate") == 0
    assert poll(setup) is None


def test_pending_collection_cannot_be_bypassed_by_diagnosis(setup):
    propose(setup)
    with pytest.raises(ValueError, match="autorisation"):
        setup.service.diagnose_incident(str(setup.incident.incident_id))
    assert setup.jobs.count("ai.inference") == 1
    assert setup.jobs.count("logs.investigate") == 0


def test_read_only_policy_collects_and_tests_without_a_pending_request(setup):
    s = setup
    s.service.followups.automatic_read_only = True
    s.expertise.investigations.read_only_snapshot = lambda node: {
        "origin": "infra-01",
        "requested_node": node,
        "endpoints": [{"target": "ha", "tcp": "OK", "http_status": 401}],
    }
    propose(s)
    assert s.service.read_companion_requests().requests == []
    followup = s.incidents.get(s.incident.incident_id).followup
    req = s.incidents.get_user_request(followup["request_id"])
    assert req.answer_source == "read_only_policy"
    assert req.answered_by == "tsunade"
    collected(s)
    review = poll(s)
    snapshot = next(
        e
        for e in review.parameters["evidence"]
        if e["source"] == "diagnostics.read_only"
    )
    assert json.loads(snapshot["content"])["origin"] == "infra-01"
    s.service.complete_job(
        str(review.job_id),
        {
            "worker_id": "worker",
            "attempt": review.attempt,
            "status": "SUCCEEDED",
            "result": ai_result(incomplete=True),
        },
    )
    assert poll(s) is None
    assert s.jobs.count("logs.investigate") == 1
    assert s.jobs.count("ai.inference") == 2


def test_completed_review_remains_visible_after_redundant_legacy_analysis(setup):
    s = setup
    propose(s)
    req = authorize(s)
    collected(s)
    review = poll(s)
    result = ai_result()
    result["verdict"] = "KO"
    result["findings"] = [
        {"code": "LOG_ANOMALY", "evidence": "logs.analysis", "confidence": 0.8}
    ]
    s.service.complete_job(
        str(review.job_id),
        {
            "worker_id": "worker",
            "attempt": review.attempt,
            "status": "SUCCEEDED",
            "result": result,
        },
    )
    assert s.incidents.get_followup(str(req.request_id))["status"] == "completed"
    # Existing production data may contain a later diagnosis without the collection.
    s.expertise.record_ai_result(s.incident.incident_id, uuid4(), result)
    incident = s.incidents.get(s.incident.incident_id)
    assert incident_assessment(incident)["state"] == "investigation_exhausted"
    with pytest.raises(ValueError, match="déjà été réévaluée"):
        s.service.diagnose_incident(str(incident.incident_id))
    # A new observation makes a new diagnosis meaningful again.
    refreshed = incident.model_copy(
        update={"last_observed_at": incident.last_observed_at + timedelta(days=1)}
    )
    assert incident_assessment(refreshed)["next_action"] == "diagnose"


@pytest.mark.parametrize(
    "change", ["expired", "resolved", "disabled", "source_removed", "limit"]
)
def test_obsolete_authorization_cannot_dispatch(setup, change):
    s = setup
    propose(s)
    req = request(s)
    if change == "expired":
        with s.incidents._connection:
            s.incidents._connection.execute(
                "UPDATE tsunade_user_requests SET expires_at=? WHERE request_id=?",
                (
                    (
                        datetime.now(ZoneInfo("Europe/Paris")) - timedelta(minutes=1)
                    ).isoformat(),
                    str(req.request_id),
                ),
            )
    elif change == "resolved":
        s.incidents.process(
            Observation(
                node="ha-01",
                service="logs",
                capability="logs.health",
                status=ObservationStatus.HEALTHY,
                success=True,
                message="OK",
                source="logs.health",
                timestamp=datetime.now(ZoneInfo("Europe/Paris")),
            )
        )
    elif change == "disabled":
        s.service.log_analysis_enabled = False
    elif change == "source_removed":
        s.service.log_sources = ()
    else:
        s.service.log_max_bytes = 1024
    with pytest.raises(ValueError):
        s.service.respond_companion_request(
            str(req.request_id), "iphone", {"choice": "AUTHORIZE"}
        )
    assert s.jobs.count("logs.investigate") == 0


def test_authorization_survives_crash_before_dispatch_and_reopen(setup, monkeypatch):
    s = setup
    propose(s)
    req = request(s)

    def crash(_payload):
        raise RuntimeError("simulated process interruption")

    monkeypatch.setattr(s.service.followups, "create_job", crash)
    with pytest.raises(RuntimeError):
        authorize(s)
    assert s.incidents.get_user_request(req.request_id).answer == "AUTHORIZE"
    s.incidents.close()
    s.incidents = TsunadeIncidentRepository(s.incidents.database_path)
    # Also reopen the distributed queue to exercise independent SQLite commits.
    s.jobs.close()
    s.jobs = DistributedJobRepository(s.jobs.path)
    s.expertise = TsunadeExpertiseService(
        incidents=s.incidents, investigations=NoProbes(), ai_dispatcher=s.jobs.create
    )
    s.service = AdministrationService(
        infrastructure_repository=s.service.infrastructure_repository,
        job_repository=s.jobs,
        incident_repository=s.incidents,
        expertise_service=s.expertise,
        log_sources=("ha-01",),
    )
    assert poll(s).type == "logs.investigate"
    assert s.jobs.count("logs.investigate") == 1
    s.jobs.close()
    s.incidents.close()


def test_crash_after_review_dispatch_does_not_duplicate_review(setup, monkeypatch):
    s = setup
    propose(s)
    authorize(s)
    original = s.service.followups.create_job

    def crash(payload):
        original(payload)
        if payload["type"] == "ai.inference":
            raise RuntimeError("crash after queue commit")

    monkeypatch.setattr(s.service.followups, "create_job", crash)
    with pytest.raises(RuntimeError):
        collected(s)
    monkeypatch.setattr(s.service.followups, "create_job", original)
    assert poll(s).type == "ai.inference"
    assert s.jobs.count("ai.inference") == 2


@pytest.mark.parametrize("status", ["FAILED", "TIMEOUT", "CANCELLED"])
def test_terminal_collection_failure_is_visible_and_stops(setup, status):
    s = setup
    propose(s)
    req = authorize(s)
    job = poll(s)
    if status == "FAILED":
        s.service.complete_job(
            str(job.job_id),
            {
                "worker_id": "worker",
                "attempt": job.attempt,
                "status": status,
                "error": {"code": "test.failure", "message": "unavailable"},
            },
        )
    elif status == "CANCELLED":
        s.jobs.cancel(str(job.job_id))
        assert poll(s) is None
    else:
        s.jobs._clock = lambda: (
            datetime.now(ZoneInfo("Europe/Paris")) + timedelta(days=1)
        )
        assert poll(s) is None
    assert s.incidents.get_followup(str(req.request_id))["status"] == "failed"
    assert s.jobs.count("ai.inference") == 1
    assert poll(s) is None


def test_companion_cannot_override_plan(setup):
    propose(setup)
    req = request(setup)
    with pytest.raises(ValueError):
        setup.service.respond_companion_request(
            str(req.request_id), "iphone", {"choice": "AUTHORIZE", "source": "other"}
        )
    assert setup.jobs.count("logs.investigate") == 0


def test_old_persisted_suggestion_is_reconciled_without_new_ai(setup):
    s = setup
    job = propose(s, crash=True)
    s.jobs.mark_completion_processed(str(job.job_id))
    assert request(s).kind == "investigation_authorization"
    assert len(s.service.read_companion_requests().requests) == 1
    assert s.jobs.count("ai.inference") == 1


def test_simultaneous_answers_only_create_one_collection(setup):
    propose(setup)
    req = request(setup)

    def answer(_):
        return setup.service.respond_companion_request(
            str(req.request_id), "iphone", {"choice": "AUTHORIZE"}
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(answer, range(2)))
    assert all(response.answer == "AUTHORIZE" for response in responses)
    assert setup.jobs.count("logs.investigate") == 1


def test_same_observations_do_not_request_consent_again_after_refusal(setup):
    s = setup
    propose(s)
    req = request(s)
    s.service.respond_companion_request(
        str(req.request_id), "iphone", {"choice": "REFUSE"}
    )
    propose(s)
    assert s.service.read_companion_requests().requests == []
    assert len(s.incidents.list_user_requests(state="all").requests) == 1


def test_stale_suggestions_do_not_create_a_new_authorization(setup):
    s = setup
    job = propose(s, crash=True)
    s.jobs.mark_completion_processed(str(job.job_id))
    s.incidents.process(
        Observation(
            node="ha-01",
            service="logs",
            capability="logs.health",
            status=ObservationStatus.DEGRADED,
            success=False,
            message="New observations",
            source="logs.health",
            timestamp=datetime.now(ZoneInfo("Europe/Paris")),
        )
    )
    assert s.service.read_companion_requests().requests == []


def test_unknown_operation_is_explained_without_execution(setup):
    s = setup
    job = propose(s, crash=True)
    s.jobs.mark_completion_processed(str(job.job_id))
    fake = SimpleNamespace(
        job_id=job.job_id,
        parameters=job.parameters,
        result={"recommended_investigation": ["Redémarrer le serveur"]},
    )
    s.service.followups.consider(fake)
    s.service.followups.consider(fake)
    assert s.incidents.list_user_requests().requests == []
    events = s.incidents.get(s.incident.incident_id).events
    assert sum(e.payload.get("status") == "unsupported" for e in events) == 1
    assert s.jobs.count("logs.investigate") == 0


def test_followup_http_requires_session_and_accepts_only_a_choice(setup, tmp_path):
    s = setup
    propose(s)
    req = request(s)
    companions = CompanionRepository(tmp_path / "companions.db")
    token = _pair(companions)
    s.service.companion_repository = companions
    server = AdministrationHTTPServer(
        service=s.service, token="admin", companion_only=True, port=0
    )
    server.start()
    path = f"/v1/incidents/requests/{req.request_id}/response"
    try:
        with pytest.raises(HTTPError) as denied:
            _companion_request(
                server, path, method="POST", payload={"choice": "AUTHORIZE"}
            )
        assert denied.value.code == 401
        with pytest.raises(HTTPError) as arbitrary:
            _companion_request(
                server,
                path,
                method="POST",
                device_id="iphone-cedric",
                token=token,
                payload={"choice": "AUTHORIZE", "command": "anything"},
            )
        assert arbitrary.value.code == 422
        assert s.jobs.count("logs.investigate") == 0
        answer = _companion_request(
            server,
            path,
            method="POST",
            device_id="iphone-cedric",
            token=token,
            payload={"choice": "AUTHORIZE"},
        )
        assert answer["answered_by"] == "iphone-cedric"
        assert s.jobs.count("logs.investigate") == 1
    finally:
        server.stop()
        companions.close()
