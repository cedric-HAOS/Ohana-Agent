"""Catalogue enrichment: teleinfo2mqtt, Z-Wave JS and chrony repairs."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ohana_agent.api.service import AdministrationService
from ohana_agent.host.chrony import ChronyRestartRequester, chrony_status
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.investigations import InvestigationResult
from ohana_agent.tsunade.repair_catalog import eligible_repair, repair_spec

# The production declarations of Konoha, read on INFRA-01 on 25 September.
INFRASTRUCTURE = """\
infrastructure: {id: konoha, name: Konoha}
nodes:
  - {id: infra-01, name: INFRA-01, endpoint: {type: ip, address: 192.168.1.10}}
  - {id: zwave-01, name: ZWAVE-01, endpoint: {type: ip, address: 192.168.1.30}}
  - {id: linky-01, name: LINKY-01, endpoint: {type: ip, address: 192.168.1.40}}
services:
  - {id: chrony, name: NTP, type: ntp, node: infra-01, implementation: NTP}
  - {id: zwave, name: Z-Wave JS, type: zwave, node: zwave-01,
     implementation: Z-Wave JS UI}
  - {id: tic-linky, name: Linky, type: teleinformation, node: linky-01,
     implementation: teleinfo2mqtt}
"""

INCIDENTS = {
    "chrony": ("infra-01", "ntp.query"),
    "zwave": ("zwave-01", "zwave.status"),
    "tic-linky": ("linky-01", "teleinformation.freshness"),
}
TELEINFO_SLUG = "6fc079ce_teleinfo2mqtt_ohana"
ZWAVE_SLUG = "a0d7b954_zwavejs2mqtt"
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
    node, capability = INCIDENTS[service]
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
        metadata={"device_id": node, "mode": "direct_http"},
    )


def _record(repository, incident, kind: str, payload: dict) -> None:
    repository.append_record(
        incident.incident_id, {"kind": kind, "summary": kind, "payload": payload}
    )


def _inspection(addons: list[dict] | None) -> dict:
    remote = {"addons": addons} if addons is not None else {"status": "unavailable"}
    return {"configuration_inspection": {"remote": remote}}


def _incident(repository, service: str, *, evidence: str, records=()):
    incident = repository.process(
        _observation(service, ObservationStatus.UNHEALTHY, STARTED)
    )
    for kind, payload in records:
        _record(repository, incident, kind, payload)
    _record(repository, incident, "diagnostic", {"epistemic_status": evidence})
    return repository.get(incident.incident_id)


def _probe(operation: str, result: dict) -> tuple[str, dict]:
    return (
        "investigation",
        {"operation": operation, "status": "OK", "result": result},
    )


def test_teleinfo_repair_targets_the_stopped_addon_listed_by_the_supervisor(
    repository, infrastructure
) -> None:
    config = infrastructure.read()
    for state in ("stopped", "error"):
        incident = _incident(
            repository,
            "tic-linky",
            evidence="confirmed_by_supervisor",
            records=[
                (
                    "investigation",
                    _inspection([{"addon": TELEINFO_SLUG, "state": state}]),
                )
            ],
        )
        spec = eligible_repair(incident, config)
        assert (spec.key, spec.operation, spec.target) == (
            "teleinfo2mqtt.restart",
            "restart_addon",
            TELEINFO_SLUG,
        )


def test_teleinfo_repair_rejects_a_started_addon(repository, infrastructure) -> None:
    config = infrastructure.read()
    started = _incident(
        repository,
        "tic-linky",
        evidence="confirmed_by_supervisor",
        records=[
            (
                "investigation",
                _inspection([{"addon": TELEINFO_SLUG, "state": "started"}]),
            )
        ],
    )
    with pytest.raises(ValueError, match="started"):
        eligible_repair(started, config)


def test_teleinfo_repair_requires_the_supervisor_confirmation(
    repository, infrastructure
) -> None:
    hypothesis = _incident(
        repository,
        "tic-linky",
        evidence="hypothesis",
        records=[
            (
                "investigation",
                _inspection([{"addon": TELEINFO_SLUG, "state": "stopped"}]),
            )
        ],
    )
    with pytest.raises(ValueError, match="confirmé par le Supervisor"):
        eligible_repair(hypothesis, infrastructure.read())


def test_zwave_repair_needs_a_failed_driver_probe_and_a_listed_addon(
    repository, infrastructure
) -> None:
    config = infrastructure.read()
    failed = _probe("zwave.status", {"success": False, "metadata": {}})
    listed = ("investigation", _inspection([{"addon": ZWAVE_SLUG, "state": "started"}]))

    incident = _incident(
        repository, "zwave", evidence="confirmed_by_probe", records=[failed, listed]
    )
    spec = eligible_repair(incident, config)
    assert (spec.key, spec.target, spec.risk) == (
        "zwave_js.restart",
        ZWAVE_SLUG,
        "medium",
    )


def test_zwave_repair_ignores_an_older_listing_when_the_supervisor_is_down(
    repository, infrastructure
) -> None:
    failed = _probe("zwave.status", {"success": False})
    incident = _incident(
        repository,
        "zwave",
        evidence="confirmed_by_probe",
        records=[
            failed,
            ("investigation", _inspection([{"addon": ZWAVE_SLUG, "state": "started"}])),
            ("investigation", _inspection(None)),
        ],
    )
    with pytest.raises(ValueError, match="Aucun add-on"):
        eligible_repair(incident, infrastructure.read())


def test_zwave_repair_is_not_proposed_on_a_healthy_driver(
    repository, infrastructure
) -> None:
    incident = _incident(
        repository,
        "zwave",
        evidence="confirmed_by_probe",
        records=[
            _probe("zwave.status", {"success": True}),
            ("investigation", _inspection([{"addon": ZWAVE_SLUG, "state": "started"}])),
        ],
    )
    with pytest.raises(ValueError, match="ne confirme pas"):
        eligible_repair(incident, infrastructure.read())


def test_chrony_repair_requires_an_inactive_local_chrony(
    repository, infrastructure
) -> None:
    config = infrastructure.read()
    stopped = _incident(
        repository,
        "chrony",
        evidence="confirmed_by_probe",
        records=[
            _probe("ntp.status", {"success": False}),
            _probe("chrony.status", {"success": False, "service_active": False}),
        ],
    )
    spec = eligible_repair(stopped, config, agent_node_id="infra-01")
    assert (spec.key, spec.operation, spec.target) == (
        "chrony.restart",
        "restart_service",
        "chrony.service",
    )
    # chrony declared on INFRA-01 is not the Agent host's chrony elsewhere.
    with pytest.raises(ValueError, match="hôte de l’Agent"):
        eligible_repair(stopped, config, agent_node_id="ha-01")


def test_chrony_repair_is_not_proposed_for_failing_upstream_sources(
    repository, infrastructure
) -> None:
    active = _incident(
        repository,
        "chrony",
        evidence="confirmed_by_probe",
        records=[
            _probe("ntp.status", {"success": False}),
            _probe("chrony.status", {"success": True, "service_active": True}),
        ],
    )
    with pytest.raises(ValueError, match="chrony.status ne confirme pas"):
        eligible_repair(active, infrastructure.read(), agent_node_id="infra-01")


def test_persisted_addon_repairs_find_their_catalogue_entry() -> None:
    assert repair_spec("restart_addon", TELEINFO_SLUG).key == "teleinfo2mqtt.restart"
    assert repair_spec("restart_addon", TELEINFO_SLUG).target == TELEINFO_SLUG
    assert repair_spec("restart_addon", ZWAVE_SLUG).key == "zwave_js.restart"
    assert repair_spec("restart_addon", "core_mosquitto").key == "mosquitto.restart"
    assert repair_spec("restart_service", "chrony.service").key == "chrony.restart"
    assert repair_spec("restart_addon", "core_zigbee2mqtt") is None
    assert repair_spec("restart_addon", "../teleinfo") is None


class NodeInvestigations:
    """Probes and Supervisor listing of one failing Konoha node."""

    def __init__(self, results: dict[str, dict], addons: list[dict]) -> None:
        self.results = results
        self.addons = addons
        self.operations: list[str] = []
        self.snapshot_nodes: list[str] = []

    def execute(self, payload):
        operation = payload["operation"]
        self.operations.append(operation)
        return InvestigationResult(
            investigation_id=uuid4(),
            operation=operation,
            status="OK",
            started_at=STARTED,
            finished_at=STARTED,
            duration_seconds=0,
            result=self.results.get(operation, {"success": True}),
        )

    def read_only_snapshot(self, node_id: str) -> dict:
        self.snapshot_nodes.append(node_id)
        return _inspection(self.addons)


def _cycle(repository, infrastructure, investigations, executed):
    def execute(incident, target):
        executed.append((incident.node_id, target))

    service = AdministrationService(
        infrastructure_repository=infrastructure,
        incident_repository=repository,
        repair_executors={
            key: execute
            for key in ("teleinfo2mqtt.restart", "zwave_js.restart", "chrony.restart")
        },
        agent_node_id="infra-01",
    )
    expertise = TsunadeExpertiseService(
        incidents=repository,
        investigations=investigations,
        ai_dispatcher=lambda payload: pytest.fail("Katsuyu must not be needed"),
    )
    expertise.set_repair_proposer(
        lambda incident_id: service.propose_incident_repair(
            str(incident_id), {}, automatic=True
        )
    )
    return service, expertise


def _authorize_and_verify(service, repository, incident, service_id):
    [repair] = repository.get(incident.incident_id).repairs
    verifying = service.authorize_incident_repair(
        str(incident.incident_id),
        {"repair_id": str(repair.repair_id), "source": "vision"},
    )
    assert verifying.status == "verifying"
    repository.process(
        _observation(service_id, ObservationStatus.HEALTHY, datetime.now(UTC))
    )
    return repository.get(incident.incident_id)


def test_stopped_teleinfo_addon_is_proposed_repaired_and_verified(
    repository, infrastructure
) -> None:
    executed: list[tuple[str, str]] = []
    investigations = NodeInvestigations(
        {}, [{"addon": TELEINFO_SLUG, "state": "stopped"}]
    )
    service, expertise = _cycle(repository, infrastructure, investigations, executed)
    incident = repository.process(
        _observation("tic-linky", ObservationStatus.UNHEALTHY, STARTED)
    )

    outcome = expertise.diagnose(incident.incident_id)

    assert outcome.decision == "action_required"
    [repair] = repository.get(incident.incident_id).repairs
    assert (repair.status, repair.target, repair.risk) == (
        "proposed",
        TELEINFO_SLUG,
        "low",
    )
    assert repair.action == "le redémarrage supervisé de l’add-on teleinfo2mqtt"
    assert executed == []

    details = _authorize_and_verify(service, repository, incident, "tic-linky")

    assert executed == [("linky-01", TELEINFO_SLUG)]
    assert details.state == "resolved"
    assert details.repairs[0].status == "succeeded"
    # The Supervisor-confirmed diagnosis can be learned like a probe one.
    assert details.experience_candidate is not None


def test_failed_zwave_driver_proposes_the_listed_addon_restart(
    repository, infrastructure
) -> None:
    executed: list[tuple[str, str]] = []
    investigations = NodeInvestigations(
        {"zwave.status": {"success": False, "message": "Connection refused"}},
        [{"addon": ZWAVE_SLUG, "state": "started"}],
    )
    service, expertise = _cycle(repository, infrastructure, investigations, executed)
    incident = repository.process(
        _observation("zwave", ObservationStatus.UNHEALTHY, STARTED)
    )

    outcome = expertise.diagnose(incident.incident_id)

    assert investigations.operations == ["zwave.status", "network.ping"]
    assert investigations.snapshot_nodes == ["zwave-01"]
    assert any(ZWAVE_SLUG in fact for fact in outcome.facts)
    details = _authorize_and_verify(service, repository, incident, "zwave")
    assert executed == [("zwave-01", ZWAVE_SLUG)]
    assert details.repairs[0].status == "succeeded"


def test_stopped_chrony_is_proposed_and_restarted_through_the_helper(
    repository, infrastructure
) -> None:
    executed: list[tuple[str, str]] = []
    investigations = NodeInvestigations(
        {
            "ntp.status": {"success": False, "error": "timed out"},
            "chrony.status": {"success": False, "service_active": False},
        },
        [],
    )
    service, expertise = _cycle(repository, infrastructure, investigations, executed)
    incident = repository.process(
        _observation("chrony", ObservationStatus.UNHEALTHY, STARTED)
    )

    expertise.diagnose(incident.incident_id)

    # A host service needs no Supervisor inspection.
    assert investigations.snapshot_nodes == []
    details = _authorize_and_verify(service, repository, incident, "chrony")
    assert executed == [("infra-01", "chrony.service")]
    assert details.repairs[0].status == "succeeded"


def test_chrony_restart_request_needs_the_installed_helper(tmp_path: Path) -> None:
    request = tmp_path / "run" / "chrony-restart.request"
    unit = tmp_path / "ohana-chrony-restart.path"
    requester = ChronyRestartRequester(request_path=request, path_unit=unit)

    with pytest.raises(RuntimeError, match="n’est pas installé"):
        requester.request_restart()
    assert not request.exists()

    unit.write_text("[Path]\n", encoding="utf-8")
    requester.request_restart()
    assert '"schema_version":1' in request.read_text(encoding="utf-8")
    assert [path.name for path in request.parent.iterdir()] == [request.name]


def test_chrony_status_reads_the_unit_without_privileges(tmp_path: Path) -> None:
    systemctl = tmp_path / "systemctl"
    systemctl.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(stdout="inactive\n", returncode=3)

    status = chrony_status(systemctl_path=systemctl, runner=runner)

    assert calls == [[str(systemctl), "is-active", "chrony.service"]]
    assert status["success"] is False
    assert status["service_active"] is False
    assert status["state"] == "inactive"
    with pytest.raises(FileNotFoundError):
        chrony_status(systemctl_path=tmp_path / "missing", runner=runner)
