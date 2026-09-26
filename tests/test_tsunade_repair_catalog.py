"""Phase 2: catalogue repairs, their preconditions and the Mosquitto repair."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from ohana_agent.api.service import AdministrationService
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade import configuration_inspection
from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.investigations import InvestigationResult
from ohana_agent.tsunade.repair_catalog import eligible_repair

INFRASTRUCTURE = """\
infrastructure: {id: konoha, name: Konoha}
nodes:
  - {id: infra-01, name: INFRA-01, endpoint: {type: ip, address: 192.168.1.10}}
  - {id: ha-01, name: HA-01, endpoint: {type: ip, address: 192.168.1.20}}
  - {id: zwave-01, name: ZWAVE-01, endpoint: {type: ip, address: 192.168.1.30}}
services:
  - {id: dhcp, name: DHCP, type: dhcp, node: infra-01, implementation: dnsmasq}
  - {id: mqtt, name: MQTT, type: mqtt, node: ha-01, implementation: Mosquitto broker}
  - {id: dns-primary, name: DNS, type: dns, node: zwave-01,
     implementation: AdGuard Home}
"""

INCIDENTS = {
    "dhcp": ("infra-01", "dhcp.status", "dhcp.status"),
    "mqtt": ("ha-01", "mqtt.roundtrip", "mqtt.status"),
    "dns-primary": ("zwave-01", "dns.resolve", "dns.query"),
}
STARTED = datetime.now(UTC) - timedelta(minutes=5)


@pytest.fixture
def repository(tmp_path: Path):
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    yield repository
    repository.close()


@pytest.fixture
def infrastructure(tmp_path: Path) -> InfrastructureConfigurationRepository:
    path = tmp_path / "infrastructure.yaml"
    path.write_text(INFRASTRUCTURE, encoding="utf-8")
    return InfrastructureConfigurationRepository(path)


def _observation(service: str, status: ObservationStatus, at: datetime):
    node, capability, _probe = INCIDENTS[service]
    return Observation(
        node=node,
        service=service,
        capability=capability,
        status=status,
        success=status is ObservationStatus.HEALTHY,
        message=f"{service} is {status.value}",
        source=capability,
        id=uuid4(),
        timestamp=at,
        metadata={"device_id": node},
    )


def _confirmed(repository, service: str, probe_result: dict, *, confirmed=True):
    incident = repository.process(
        _observation(service, ObservationStatus.UNHEALTHY, STARTED)
    )
    repository.append_record(
        incident.incident_id,
        {
            "kind": "investigation",
            "summary": "probe",
            "payload": {
                "operation": INCIDENTS[service][2],
                "status": "OK",
                "result": probe_result,
            },
        },
    )
    repository.append_record(
        incident.incident_id,
        {
            "kind": "diagnostic",
            "summary": "diagnostic",
            "payload": {
                "epistemic_status": "confirmed_by_probe" if confirmed else "hypothesis"
            },
        },
    )
    return repository.get(incident.incident_id)


STOPPED = {"success": False, "metadata": {"service_active": False}}
REFUSED = {"success": False, "message": "[Errno 111] Connection refused"}


def test_catalogue_selects_repairs_from_declared_services(
    repository, infrastructure
) -> None:
    config = infrastructure.read()
    dhcp = _confirmed(repository, "dhcp", STOPPED)
    assert eligible_repair(dhcp, config).key == "dnsmasq.restart"
    mqtt = _confirmed(repository, "mqtt", REFUSED)
    spec = eligible_repair(mqtt, config)
    assert (spec.key, spec.operation, spec.target) == (
        "mosquitto.restart",
        "restart_addon",
        "core_mosquitto",
    )
    # An AdGuard DNS failure used to match the "dns" keyword and propose a
    # dnsmasq restart on INFRA-01: the wrong service entirely.
    adguard = _confirmed(repository, "dns-primary", {"success": False})
    with pytest.raises(ValueError, match="Aucune réparation connue"):
        eligible_repair(adguard, config)


def test_preconditions_require_the_confirming_probe(repository, infrastructure):
    config = infrastructure.read()
    full_pool = _confirmed(
        repository, "dhcp", {"success": False, "metadata": {"service_active": True}}
    )
    with pytest.raises(ValueError, match="ne confirme pas"):
        eligible_repair(full_pool, config)


def test_hypothesis_is_not_enough_for_a_repair(repository, infrastructure) -> None:
    mqtt = _confirmed(repository, "mqtt", REFUSED, confirmed=False)
    with pytest.raises(ValueError, match="confirmé par une sonde"):
        eligible_repair(mqtt, infrastructure.read())


def _service(repository, infrastructure, executed, *, fail=False):
    def restart(incident, target):
        executed.append((incident.node_id, target))
        if fail:
            raise RuntimeError("Le Supervisor a refusé le redémarrage")

    return AdministrationService(
        infrastructure_repository=infrastructure,
        incident_repository=repository,
        repair_executors={"mosquitto.restart": restart},
    )


def test_mosquitto_repair_runs_once_after_authorization_and_is_verified(
    repository, infrastructure
) -> None:
    executed: list[tuple[str, str]] = []
    service = _service(repository, infrastructure, executed)
    incident = _confirmed(repository, "mqtt", REFUSED)

    repair = service.propose_incident_repair(str(incident.incident_id), {})
    assert repair.status == "proposed"
    assert repair.action == "le redémarrage supervisé de l’add-on Mosquitto"
    assert executed == []  # A proposal never executes anything.
    request = repository.list_user_requests().requests[0]
    assert "Mosquitto" in request.question

    verifying = service.authorize_incident_repair(
        str(incident.incident_id),
        {"repair_id": str(repair.repair_id), "source": "vision"},
    )
    assert verifying.status == "verifying"
    assert executed == [("ha-01", "core_mosquitto")]

    repository.process(
        _observation("mqtt", ObservationStatus.HEALTHY, datetime.now(UTC))
    )
    details = repository.get(incident.incident_id)
    assert details.state == "resolved"
    assert details.repairs[0].status == "succeeded"
    assert details.experience_candidate is not None


def test_supervisor_refusal_leaves_an_explicit_failure(
    repository, infrastructure
) -> None:
    executed: list[tuple[str, str]] = []
    service = _service(repository, infrastructure, executed, fail=True)
    incident = _confirmed(repository, "mqtt", REFUSED)
    repair = service.propose_incident_repair(str(incident.incident_id), {})

    failed = service.authorize_incident_repair(
        str(incident.incident_id),
        {"repair_id": str(repair.repair_id), "source": "vision"},
    )
    assert failed.status == "failed"
    assert "Supervisor a refusé" in failed.result
    assert repository.get(incident.incident_id).state == "active"
    # Tsunade does not propose it again by itself after this decision.
    assert (
        service.propose_incident_repair(str(incident.incident_id), {}, automatic=True)
        is None
    )
    assert executed == [("ha-01", "core_mosquitto")]


def test_repair_without_configured_executor_is_not_proposed(
    repository, infrastructure
) -> None:
    service = AdministrationService(
        infrastructure_repository=infrastructure,
        incident_repository=repository,
    )
    incident = _confirmed(repository, "mqtt", REFUSED)
    with pytest.raises(LookupError, match="n’est pas configurée"):
        service.propose_incident_repair(str(incident.incident_id), {})
    assert repository.get(incident.incident_id).repairs == []


class RefusedMqtt:
    def execute(self, payload):
        return InvestigationResult(
            investigation_id=uuid4(),
            operation=payload["operation"],
            status="OK",
            started_at=STARTED,
            finished_at=STARTED,
            duration_seconds=0,
            result=REFUSED if payload["operation"] == "mqtt.status" else {},
        )


def test_tsunade_proposes_the_repair_after_a_confirmed_diagnosis(
    repository, infrastructure
) -> None:
    service = _service(repository, infrastructure, [])
    expertise = TsunadeExpertiseService(
        incidents=repository,
        investigations=RefusedMqtt(),  # type: ignore[arg-type]
    )
    expertise.set_repair_proposer(
        lambda incident_id: service.propose_incident_repair(
            str(incident_id), {}, automatic=True
        )
    )
    incident = repository.process(
        _observation("mqtt", ObservationStatus.UNHEALTHY, STARTED)
    )

    assert expertise.diagnose(incident.incident_id).status == "DETERMINISTIC"
    repairs = repository.get(incident.incident_id).repairs
    assert [(item.status, item.target) for item in repairs] == [
        ("proposed", "core_mosquitto")
    ]


def test_restart_addon_posts_to_the_supervisor_and_reports_refusal(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str, object]] = []
    replies = [
        {"success": True},
        {"success": False, "error": {"message": "busy"}},
        {"success": False, "error": {"code": "unknown_error", "message": ""}},
    ]

    @asynccontextmanager
    async def fake_api(config, node_id, *, timeout_seconds=8):
        async def call(endpoint, method, **options):
            calls.append((endpoint, method, options.get("timeout", "default")))
            return replies.pop(0)

        yield call

    monkeypatch.setattr(configuration_inspection, "supervisor_api", fake_api)
    configuration_inspection.restart_addon(object(), "ha-01", "core_mosquitto")
    with pytest.raises(RuntimeError, match="busy"):
        configuration_inspection.restart_addon(object(), "ha-01", "core_mosquitto")
    with pytest.raises(RuntimeError, match="unknown_error"):
        configuration_inspection.restart_addon(object(), "ha-01", "core_mosquitto")
    # Home Assistant is always told to wait for the Supervisor itself.
    assert calls == [("/addons/core_mosquitto/restart", "post", None)] * 3
    with pytest.raises(ValueError, match="invalide"):
        configuration_inspection.restart_addon(object(), "ha-01", "../core")


def _home_assistant_api(restart_seconds: float, calls: list):
    """Answer like Home Assistant: give up at 10 s unless told otherwise."""

    @asynccontextmanager
    async def fake_api(config, node_id, *, timeout_seconds=8):
        async def call(endpoint, method, **options):
            timeout = options.get("timeout", 10)
            calls.append(timeout)
            if timeout is not None and timeout < restart_seconds:
                # The Supervisor keeps restarting; HA reports a bare error.
                return {"success": False, "error": {"code": "unknown_error"}}
            await asyncio.sleep(min(restart_seconds, 0.01))
            return {"success": True}

        yield call

    return fake_api


def test_slow_addon_restart_is_not_reported_as_a_refusal(monkeypatch) -> None:
    # Z-Wave JS UI took about a minute on Konoha: 1.35.1 sent no timeout and
    # declared a failure 10 s after the authorization, the add-on came back.
    calls: list = []
    monkeypatch.setattr(
        configuration_inspection, "supervisor_api", _home_assistant_api(60, calls)
    )

    configuration_inspection.restart_addon(
        object(), "zwave-01", "a0d7b954_zwavejs2mqtt"
    )

    assert calls == [None]


def test_restart_still_running_after_the_wait_is_left_to_shikamaru(
    monkeypatch,
) -> None:
    monkeypatch.setattr(configuration_inspection, "ADDON_RESTART_WAIT_SECONDS", 0.05)

    @asynccontextmanager
    async def slow_api(config, node_id, *, timeout_seconds=8):
        async def call(endpoint, method, **options):
            await asyncio.sleep(1)
            return {"success": True}

        yield call

    monkeypatch.setattr(configuration_inspection, "supervisor_api", slow_api)

    # Returns normally: the repair goes to verification, not to failure.
    configuration_inspection.restart_addon(
        object(), "zwave-01", "a0d7b954_zwavejs2mqtt"
    )


def test_unreachable_supervisor_still_fails_the_execution(monkeypatch) -> None:
    monkeypatch.setattr(configuration_inspection, "ADDON_RESTART_WAIT_SECONDS", 0.05)

    @asynccontextmanager
    async def unreachable_api(config, node_id, *, timeout_seconds=8):
        await asyncio.sleep(1)
        yield None

    monkeypatch.setattr(configuration_inspection, "supervisor_api", unreachable_api)

    with pytest.raises(TimeoutError):
        configuration_inspection.restart_addon(
            object(), "zwave-01", "a0d7b954_zwavejs2mqtt"
        )


def test_vision_deferral_keeps_the_proposal_pending_without_executing(
    repository, infrastructure
) -> None:
    executed: list[tuple[str, str]] = []
    service = _service(repository, infrastructure, executed)
    incident = _confirmed(repository, "mqtt", REFUSED)
    repair = service.propose_incident_repair(str(incident.incident_id), {})

    deferred = service.defer_incident_repair(
        str(incident.incident_id),
        {"repair_id": str(repair.repair_id), "source": "vision"},
    )

    assert deferred.status == "proposed"
    assert deferred.deferred_until is not None
    assert deferred.deferred_until.utcoffset() is not None
    assert executed == []
    [request] = repository.list_user_requests().requests
    assert request.state == "pending"
    assert request.deferred_until == deferred.deferred_until
    # The user may still decide during the deferral; only then does it run.
    service.authorize_incident_repair(
        str(incident.incident_id),
        {"repair_id": str(repair.repair_id), "source": "vision"},
    )
    assert executed == [("ha-01", "core_mosquitto")]


def test_vision_refusal_is_final_and_never_executes(repository, infrastructure):
    executed: list[tuple[str, str]] = []
    service = _service(repository, infrastructure, executed)
    incident = _confirmed(repository, "mqtt", REFUSED)
    repair = service.propose_incident_repair(str(incident.incident_id), {})

    refused = service.refuse_incident_repair(
        str(incident.incident_id),
        {"repair_id": str(repair.repair_id), "source": "vision"},
    )

    assert refused.status == "refused"
    with pytest.raises(ValueError, match="n’attend plus"):
        service.authorize_incident_repair(
            str(incident.incident_id),
            {"repair_id": str(repair.repair_id), "source": "vision"},
        )
    with pytest.raises(ValueError, match="n’attend plus"):
        service.defer_incident_repair(
            str(incident.incident_id),
            {"repair_id": str(repair.repair_id), "source": "vision"},
        )
    assert (
        service.propose_incident_repair(str(incident.incident_id), {}, automatic=True)
        is None
    )
    assert executed == []
