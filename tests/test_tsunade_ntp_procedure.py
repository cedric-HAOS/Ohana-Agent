"""NTP has a deterministic procedure instead of an AI escalation."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository
from ohana_agent.tsunade.investigations import InvestigationResult

STARTED = datetime(2026, 9, 25, 15, tzinfo=UTC)


class Probes:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def execute(self, payload):
        self.operations.append(payload["operation"])
        return InvestigationResult(
            investigation_id=uuid4(),
            operation=payload["operation"],
            status="OK",
            started_at=STARTED,
            finished_at=STARTED,
            duration_seconds=0,
            result={"success": False, "error": "timed out"},
        )


def _incident(repository, service: str, capability: str, message: str):
    return repository.process(
        Observation(
            node="infra-01",
            service=service,
            capability=capability,
            status=ObservationStatus.UNHEALTHY,
            success=False,
            message=message,
            source=capability,
            id=uuid4(),
            timestamp=STARTED,
            metadata={"device_id": "infra-01"},
        )
    )


def test_stopped_chrony_is_confirmed_without_katsuyu(tmp_path: Path) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    dispatched: list[dict] = []
    probes = Probes()
    try:
        incident = _incident(
            repository, "chrony", "ntp.query", "NTP query to 127.0.0.1 timed out."
        )
        service = TsunadeExpertiseService(
            incidents=repository,
            investigations=probes,  # type: ignore[arg-type]
            ai_dispatcher=lambda payload: (
                dispatched.append(payload) or SimpleNamespace(job_id=uuid4())
            ),
        )

        outcome = service.diagnose(incident.incident_id)

        # chrony.status tells a stopped chrony from failing upstream sources.
        assert probes.operations == ["ntp.status", "chrony.status"]
        assert outcome.status == "DETERMINISTIC"
        assert outcome.decision == "action_required"
        assert "requête NTP" in outcome.diagnosis
        assert dispatched == []
        decision = repository.get(incident.incident_id).latest_decision
        assert decision["epistemic_status"] == "confirmed_by_probe"
    finally:
        repository.close()


def test_mountpoint_message_does_not_select_the_ntp_procedure() -> None:
    incident = SimpleNamespace(
        service_id="disk",
        capability_id="disk.usage",
        message="Root mountpoint is 95 % full",
    )
    procedure = TsunadeExpertiseService._known_procedure(incident)  # noqa: SLF001
    assert procedure is not None
    assert procedure.operations == ("disk.usage",)
