"""Exercise the real inspection/snapshot/diagnosis chain with a fake transport."""

import json
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.configuration_inspection import inspect_configuration
from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.investigations import InvestigationExecutor


@pytest.mark.parametrize(
    "case",
    [
        "stopped",
        "started",
        "stats_unavailable",
        "auth_rejected",
        "timeout",
        "snapshot_error",
        "busy",
    ],
)
def test_supervisor_evidence_survives_restart_and_reaches_ai(
    tmp_path, monkeypatch, case, caplog
):
    requests = []
    slug = "sandbox_teleinfo2mqtt"

    class Socket:
        async def __aenter__(self):
            self.stage = 0
            self.request = None
            return self

        async def __aexit__(self, *_args):
            pass

        async def send_json(self, request):
            requests.append(request)
            self.request = request

        async def receive_json(self):
            self.stage += 1
            if self.stage == 1:
                return {"type": "auth_required"}
            if self.stage == 2:
                return {
                    "type": "auth_invalid" if case == "auth_rejected" else "auth_ok"
                }
            endpoint = self.request["endpoint"]
            assert self.request["method"] == "get"
            if case == "timeout":
                raise TimeoutError("Bearer private-secret-value")
            results = {
                "/addons": {"addons": [{"slug": slug}]},
                "/hardware/info": {},
                f"/addons/{slug}/info": {
                    "slug": slug,
                    "state": "started" if case == "started" else "stopped",
                    "options": {"OHANA_TOKEN": "private-secret-value"},
                },
                f"/addons/{slug}/stats": {},
                "/core/info": {},
            }
            assert endpoint in results
            return {
                "success": not (
                    case == "stats_unavailable" and endpoint.endswith("/stats")
                ),
                "result": results[endpoint],
            }

    class Session:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        def ws_connect(self, url, **_kwargs):
            assert url == "https://sandbox.invalid/api/websocket".replace(
                "https", "wss"
            )
            return Socket()

    monkeypatch.setattr(
        "ohana_agent.tsunade.configuration_inspection.aiohttp.ClientSession", Session
    )
    config = SimpleNamespace(
        targets=[
            SimpleNamespace(
                id="linky-01",
                enabled=True,
                token="private-secret-value",
                url="https://sandbox.invalid",
                verify_tls=True,
            )
        ]
    )
    infrastructure = InfrastructureConfig.model_validate(
        {"infrastructure": {"id": "sandbox", "name": "Sandbox"}}
    )
    executor = InvestigationExecutor(
        plugins=None,
        host_health_reader=lambda: {},
        infrastructure_reader=lambda: infrastructure,
        configuration_reader=lambda node: inspect_configuration(None, config, node),
    )
    database = tmp_path / "incidents.db"
    if case == "snapshot_error":

        def fail_snapshot(_node):
            raise RuntimeError("Bearer private-secret-value")

        monkeypatch.setattr(executor, "read_only_snapshot", fail_snapshot)
    elif case == "busy":
        monkeypatch.setattr(
            executor,
            "read_only_snapshot",
            lambda _node: {"configuration_inspection": {"status": "busy"}},
        )
    repository = TsunadeIncidentRepository(database)
    dispatched = []

    def dispatch(payload):
        dispatched.append(payload)
        return SimpleNamespace(job_id=uuid4())

    try:
        incident = repository.process(
            Observation(
                node="linky-01",
                service="tic-linky",
                capability="teleinformation.freshness",
                source="teleinformation.freshness",
                status=ObservationStatus.UNHEALTHY,
                success=False,
                message="Aucune trame depuis 85 secondes",
                timestamp=datetime.now(ZoneInfo("Europe/Paris")),
                metadata={"mode": "direct_http", "device_id": "linky-01"},
            )
        )
        outcome = TsunadeExpertiseService(
            incidents=repository, investigations=executor, ai_dispatcher=dispatch
        ).diagnose(incident.incident_id, log_result={"findings": []})
    finally:
        repository.close()

    repository = TsunadeIncidentRepository(database)
    try:
        persisted = repository.get(incident.incident_id)
        evidence = [
            e
            for e in persisted.events
            if e.payload.get("source") == "supervisor.teleinformation"
        ]
        assert len(evidence) == 1
        payload = evidence[0].payload
        assert payload["node"] == "linky-01"
        if case not in {"snapshot_error", "busy"}:
            assert payload["observed_at"]
        assert payload["recorded_at"]
        remote = payload["configuration_inspection"].get("remote", {})
        assert "private-secret-value" not in persisted.model_dump_json()
        assert "private-secret-value" not in json.dumps(dispatched)
        assert "private-secret-value" not in caplog.text
        if case == "snapshot_error":
            assert payload["error"] == "RuntimeError"
            assert payload["status"] == "unavailable"
        elif case == "busy":
            assert payload["configuration_inspection"]["status"] == "busy"
        if case in {"stopped", "stats_unavailable"}:
            assert remote["addons"][0]["state"] == "stopped"
            assert persisted.latest_decision["diagnostic_level"] == "CONFIRMED"
            assert outcome.status == "DETERMINISTIC"
            assert dispatched == []
        else:
            assert outcome.status == "AI_QUEUED"
            assert persisted.latest_decision.get("diagnostic_level") != "CONFIRMED"
            ai_evidence = next(
                e
                for e in dispatched[0]["parameters"]["evidence"]
                if e["source"] == "supervisor.teleinformation"
            )
            assert json.loads(ai_evidence["content"]) == {
                k: v for k, v in payload.items() if k != "source"
            }
            if case in {"auth_rejected", "timeout"}:
                assert remote["status"] == "unavailable"
                assert remote["error"] == (
                    "ValueError" if case == "auth_rejected" else "TimeoutError"
                )
    finally:
        repository.close()
