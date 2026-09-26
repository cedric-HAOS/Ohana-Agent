"""A name lookup failure is attached to DNS or dnsmasq, never repaired locally."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.runtime.administration_bootstrap import TsunadeObservationHandler
from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.incident_correlation import (
    is_name_resolution_failure,
    name_resolution_providers,
)
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.investigations import InvestigationResult

# 26 September, 17:25:42: dnsmasq stopped on INFRA-01.
STARTED = datetime(2026, 9, 26, 17, 25, 42, tzinfo=UTC)
ZWAVE_LOOKUP = (
    "Z-Wave JS Server connection failed: Cannot connect to host "
    "zwave-01.ohana.lan:3000 ssl:default [No address associated with hostname]"
)
INFRASTRUCTURE = InfrastructureConfig.model_validate(
    {
        "infrastructure": {"id": "konoha", "name": "Konoha"},
        "nodes": [
            {
                "id": node,
                "name": node,
                "endpoint": {"type": "host", "address": f"{node}.ohana.lan"},
            }
            for node in ("infra-01", "zwave-01")
        ],
        "services": [
            {
                "id": "dhcp",
                "name": "DHCP",
                "type": "dhcp",
                "node": "infra-01",
                "implementation": "dnsmasq",
            },
            {
                "id": "zwave",
                "name": "Z-Wave JS",
                "type": "zwave",
                "node": "zwave-01",
                "implementation": "Z-Wave JS UI",
            },
        ],
    }
)


def _observation(node, service, capability, message, at) -> Observation:
    return Observation(
        node=node,
        service=service,
        capability=capability,
        status=ObservationStatus.UNHEALTHY,
        success=False,
        message=message,
        source=capability,
        id=uuid4(),
        timestamp=at,
        metadata={"device_id": node},
    )


def _zwave(repository, message=ZWAVE_LOOKUP):
    return repository.process(
        _observation(
            "zwave-01",
            "zwave",
            "zwave.status",
            message,
            STARTED + timedelta(seconds=41),
        )
    )


def _dnsmasq(repository):
    return repository.process(
        _observation(
            "infra-01",
            "dhcp",
            "dhcp.status",
            "DHCP service is not active: inactive",
            STARTED + timedelta(seconds=45),
        )
    )


class Investigations:
    infrastructure_reader = staticmethod(lambda: INFRASTRUCTURE)

    def __init__(self) -> None:
        self.snapshots: list[str] = []

    def execute(self, payload):
        return InvestigationResult(
            investigation_id=uuid4(),
            operation=payload["operation"],
            status="OK",
            started_at=STARTED,
            finished_at=STARTED,
            duration_seconds=0,
            result={"success": False},  # zwave.status fails: the name is unknown
        )

    def read_only_snapshot(self, node_id: str) -> dict:
        self.snapshots.append(node_id)
        return {"configuration_inspection": {"remote": {"addons": []}}}


@pytest.fixture
def repository(tmp_path: Path):
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    yield repository
    repository.close()


def _service(repository, proposed, dispatched):
    service = TsunadeExpertiseService(
        incidents=repository,
        investigations=Investigations(),  # type: ignore[arg-type]
        ai_dispatcher=lambda payload: (
            dispatched.append(payload) or SimpleNamespace(job_id=uuid4())
        ),
    )
    service.set_repair_proposer(proposed.append)
    service.upstream_wait_seconds = 0
    return service


def test_konoha_lookup_messages_are_recognised() -> None:
    for message in (
        "[Errno -2] Name or service not known",
        "<urlopen error [Errno -2] Name or service not known>",
        ZWAVE_LOOKUP,
        "[Errno -3] Temporary failure in name resolution",
    ):
        assert is_name_resolution_failure(message)
    assert not is_name_resolution_failure("[Errno 111] Connection refused")
    assert not is_name_resolution_failure("timed out")
    assert name_resolution_providers(INFRASTRUCTURE, "zwave") == ("dhcp",)


def test_lookup_failure_is_attached_to_the_dnsmasq_incident(repository) -> None:
    proposed: list = []
    dispatched: list = []
    upstream = _dnsmasq(repository)
    symptom = _zwave(repository)

    outcome = _service(repository, proposed, dispatched).diagnose(symptom.incident_id)

    decision = repository.get(symptom.incident_id).latest_decision
    assert outcome.decision == "watch"
    assert decision["epistemic_status"] == "correlated_with_upstream"
    assert decision["upstream_incident_id"] == str(upstream.incident_id)
    assert "résoudre un nom" in decision["conclusion"]
    assert proposed == [] and dispatched == []


def test_lookup_failure_never_proposes_the_service_repair(repository) -> None:
    # Before 1.36 the failed zwave.status probe led to the known procedure and
    # a Z-Wave JS add-on restart, which cannot fix a missing resolver.
    proposed: list = []
    symptom = _zwave(repository)

    outcome = _service(repository, proposed, []).diagnose(symptom.incident_id)

    assert outcome.decision == "action_required"
    assert proposed == []
    assert any("résolution de nom" in fact for fact in outcome.facts)


def test_refused_connection_still_follows_the_known_procedure(repository) -> None:
    proposed: list = []
    symptom = _zwave(
        repository, "Z-Wave JS Server connection failed: Connect call failed"
    )

    _service(repository, proposed, []).diagnose(symptom.incident_id)

    assert proposed == [symptom.incident_id]


class RecordingExpertise:
    def __init__(self) -> None:
        self.started: list = []

    def start(self, incident_id, **_kwargs) -> None:
        self.started.append(incident_id)


def test_first_lookup_failure_requests_dns_and_dhcp_observations(repository) -> None:
    requested: list[bool] = []
    handler = TsunadeObservationHandler(
        incidents=repository,
        expertise=RecordingExpertise(),  # type: ignore[arg-type]
        administration=SimpleNamespace(),  # type: ignore[arg-type]
        logs_config=SimpleNamespace(enabled=False, sources=()),  # type: ignore[arg-type]
        notifications=None,
        on_name_lookup_failure=lambda: requested.append(True),
    )
    lookup = _observation("zwave-01", "zwave", "zwave.status", ZWAVE_LOOKUP, STARTED)

    handler(SimpleNamespace(observation=lookup))
    handler(
        SimpleNamespace(
            observation=_observation(
                "zwave-01",
                "zwave",
                "zwave.status",
                ZWAVE_LOOKUP,
                STARTED + timedelta(minutes=2),
            )
        )
    )
    handler(
        SimpleNamespace(
            observation=_observation(
                "ha-01",
                "mqtt",
                "mqtt.roundtrip",
                "[Errno 111] Connection refused",
                STARTED,
            )
        )
    )

    assert requested == [True]
