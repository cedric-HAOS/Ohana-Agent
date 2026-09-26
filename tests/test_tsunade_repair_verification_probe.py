"""Shikamaru verifies a repair right after it runs, not at the next cycle."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ohana_agent.api.service import AdministrationService
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.scheduler import (
    DryRunTaskExecutor,
    FakeClock,
    IntervalTrigger,
    Scheduler,
    Task,
)
from ohana_agent.tsunade.incident_repairs import (
    REPAIR_SETTLE_SECONDS,
    REPAIR_VERIFICATION_PROBES,
    observes_repaired_service,
)
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.repair_catalog import repair_spec

NOW = datetime(2026, 9, 26, 16, 28, tzinfo=UTC)
INFRASTRUCTURE = """\
infrastructure: {id: konoha, name: Konoha}
nodes:
  - {id: infra-01, name: INFRA-01, endpoint: {type: ip, address: 192.168.1.10}}
services:
  - {id: chrony, name: NTP, type: ntp, node: infra-01, implementation: NTP}
"""


def _ntp_task(node_id: str = "infra-01", service_id: str = "chrony") -> Task:
    # Konoha observes NTP hourly: the next scheduled run is far away.
    return Task(
        id=f"ntp.query:{service_id}",
        command="ntp.query",
        trigger=IntervalTrigger(interval=timedelta(hours=1), start_at=NOW),
        metadata={"managed_by": "ntp", "node_id": node_id, "service_id": service_id},
    )


class RecordingExecutor(DryRunTaskExecutor):
    def __init__(self) -> None:
        self.runs: list[tuple[str, datetime]] = []

    def execute(self, task, now):
        self.runs.append((task.id, now))
        return super().execute(task, now)


def test_requested_run_is_due_once_without_waiting_for_the_trigger() -> None:
    task = _ntp_task()
    task.mark_finished(NOW)
    task.request_run(NOW + timedelta(seconds=20))

    assert not task.is_due(NOW + timedelta(seconds=19))
    assert task.is_due(NOW + timedelta(seconds=20))
    task.mark_finished(NOW + timedelta(seconds=20))
    assert task.run_requests == ()
    assert not task.is_due(NOW + timedelta(seconds=21))


def test_scheduler_runs_the_tasks_of_the_repaired_service_only() -> None:
    clock = FakeClock(NOW)
    executor = RecordingExecutor()
    scheduler = Scheduler(clock=clock, executor=executor)
    repaired, other = _ntp_task(), _ntp_task(service_id="ntp-secondary")
    other_node = _ntp_task(node_id="zwave-01", service_id="chrony-zwave")
    other_node.metadata["service_id"] = "chrony"
    disabled = _ntp_task(service_id="chrony-disabled")
    disabled.metadata["service_id"] = "chrony"
    disabled.disable()
    for task in (repaired, other, other_node, disabled):
        scheduler.add_task(task)
    scheduler.start()
    scheduler.tick()  # The hourly cycle at NOW.
    executor.runs.clear()
    incident = SimpleNamespace(node_id="infra-01", service_id="chrony")

    requested = scheduler.request_runs(
        lambda task: observes_repaired_service(incident, task.metadata),
        REPAIR_VERIFICATION_PROBES,
    )

    assert requested == [repaired.id]
    for delay in (
        timedelta(seconds=10),
        *REPAIR_VERIFICATION_PROBES,
        timedelta(minutes=5),
    ):
        clock.current_time = NOW + delay
        scheduler.tick()
    assert executor.runs == [
        (repaired.id, NOW + delay) for delay in REPAIR_VERIFICATION_PROBES
    ]


def test_task_without_node_still_observes_the_repaired_service() -> None:
    incident = SimpleNamespace(node_id="infra-01", service_id="chrony")

    assert observes_repaired_service(incident, {"service_id": "chrony"})
    assert observes_repaired_service(
        incident, {"service_id": "chrony", "node_id": None}
    )
    assert not observes_repaired_service(incident, {"service_id": "dhcp"})


def _observation(status: ObservationStatus, at: datetime) -> Observation:
    return Observation(
        node="infra-01",
        service="chrony",
        capability="ntp.query",
        status=status,
        success=status is ObservationStatus.HEALTHY,
        message=f"NTP is {status.value}",
        source="ntp.query",
        id=uuid4(),
        timestamp=at,
        metadata={"device_id": "infra-01"},
    )


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


def _executed(repository):
    started = datetime.now(UTC) - timedelta(minutes=5)
    incident = repository.process(_observation(ObservationStatus.UNHEALTHY, started))
    repair = repository.propose_repair(
        incident.incident_id, repair_spec("restart_service", "chrony.service")
    )
    repository.authorize_repair(
        incident.incident_id, {"repair_id": str(repair.repair_id), "source": "vision"}
    )
    return incident, repository.mark_repair_executed(repair.repair_id)


def test_degraded_probe_while_the_service_starts_does_not_fail_the_repair(
    repository,
) -> None:
    incident, repair = _executed(repository)
    starting = repair.executed_at + timedelta(seconds=REPAIR_SETTLE_SECONDS - 1)
    repository.process(_observation(ObservationStatus.UNHEALTHY, starting))
    assert repository.get_repair(repair.repair_id).status == "verifying"

    repository.process(
        _observation(ObservationStatus.HEALTHY, starting + timedelta(seconds=15))
    )
    details = repository.get(incident.incident_id)
    assert details.repairs[0].status == "succeeded"
    assert details.state == "resolved"


def test_degraded_probe_after_the_settle_delay_fails_the_repair(repository) -> None:
    _, repair = _executed(repository)
    settled = repair.executed_at + timedelta(seconds=REPAIR_SETTLE_SECONDS + 15)
    repository.process(_observation(ObservationStatus.UNHEALTHY, settled))
    assert repository.get_repair(repair.repair_id).status == "failed"


def test_healthy_probe_right_after_execution_confirms_the_repair(repository) -> None:
    _, repair = _executed(repository)
    repository.process(
        _observation(
            ObservationStatus.HEALTHY, repair.executed_at + timedelta(seconds=20)
        )
    )
    assert repository.get_repair(repair.repair_id).status == "succeeded"


def _service(repository, infrastructure, requested, executor=None):
    return AdministrationService(
        infrastructure_repository=infrastructure,
        incident_repository=repository,
        repair_executors={"chrony.restart": executor or (lambda *_: None)},
        repair_verification_requester=requested.append,
        agent_node_id="infra-01",
    )


def _proposed(service, repository):
    incident = repository.process(
        _observation(ObservationStatus.UNHEALTHY, datetime.now(UTC))
    )
    repair = repository.propose_repair(
        incident.incident_id, repair_spec("restart_service", "chrony.service")
    )
    return incident, repair


def test_execution_requests_the_verification_of_the_repaired_capability(
    repository, infrastructure
) -> None:
    requested: list = []
    service = _service(repository, infrastructure, requested)
    incident, repair = _proposed(service, repository)

    verifying = service.authorize_incident_repair(
        str(incident.incident_id),
        {"repair_id": str(repair.repair_id), "source": "vision"},
    )

    assert verifying.status == "verifying"
    assert [(item.node_id, item.service_id) for item in requested] == [
        ("infra-01", "chrony")
    ]


def test_failed_execution_requests_no_verification(repository, infrastructure) -> None:
    requested: list = []

    def refuse(*_):
        raise RuntimeError("helper absent")

    service = _service(repository, infrastructure, requested, refuse)
    incident, repair = _proposed(service, repository)

    failed = service.authorize_incident_repair(
        str(incident.incident_id),
        {"repair_id": str(repair.repair_id), "source": "vision"},
    )

    assert failed.status == "failed"
    assert requested == []


def test_unavailable_verification_request_keeps_the_repair_verifying(
    repository, infrastructure
) -> None:
    service = _service(repository, infrastructure, [])

    def unavailable(_incident):
        raise RuntimeError("scheduler stopped")

    service.repair_verification_requester = unavailable
    incident, repair = _proposed(service, repository)

    verifying = service.authorize_incident_repair(
        str(incident.incident_id),
        {"repair_id": str(repair.repair_id), "source": "vision"},
    )

    assert verifying.status == "verifying"
