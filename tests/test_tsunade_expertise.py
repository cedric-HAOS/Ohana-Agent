"""Tests for Tsunade's deterministic-first, optional-AI expertise cycle."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from administration.expertise import TsunadeExpertiseService
from administration.incidents import TsunadeIncidentRepository
from administration.investigations import InvestigationResult
from observer import Observation, ObservationStatus


def _incident(
    repository: TsunadeIncidentRepository,
    *,
    node: str = "infra-01",
    service: str = "dns",
    capability: str = "dns.resolve",
):
    return repository.process(
        Observation(
            node=node,
            service=service,
            capability=capability,
            status=ObservationStatus.UNHEALTHY,
            success=False,
            message=f"{service} is unhealthy",
            source=capability,
            id=uuid4(),
            timestamp=datetime(2026, 8, 24, 12, tzinfo=UTC),
            metadata={"device_id": node},
        )
    )


class FakeInvestigations:
    def __init__(self, result: dict[str, object] | None = None) -> None:
        self.result = result or {}
        self.operations: list[str] = []

    def execute(self, payload):
        self.operations.append(payload["operation"])
        now = datetime(2026, 8, 24, 12, tzinfo=UTC)
        return InvestigationResult(
            investigation_id=uuid4(),
            operation=payload["operation"],
            status="OK",
            started_at=now,
            finished_at=now,
            duration_seconds=0,
            result=self.result,
        )


def test_known_procedure_stays_deterministic_when_probe_confirms_failure(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    incident = _incident(repository)
    assert incident is not None
    investigations = FakeInvestigations({"success": False})
    dispatched: list[dict[str, object]] = []
    service = TsunadeExpertiseService(
        incidents=repository,
        investigations=investigations,  # type: ignore[arg-type]
        ai_dispatcher=lambda payload: dispatched.append(payload),
    )
    try:
        outcome = service.diagnose(incident.incident_id)
        updated = repository.get(incident.incident_id)
    finally:
        repository.close()

    assert outcome.status == "DETERMINISTIC"
    assert outcome.known_procedure is True
    assert investigations.operations == ["dns.query", "network.ping"]
    assert dispatched == []
    assert updated.final_result is None
    assert updated.events[-2].payload["epistemic_status"] == "confirmed_by_probe"
    assert updated.events[-1].payload["authorized"] is False


def test_unexplained_logs_queue_only_bounded_ai_evidence(tmp_path: Path) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    incident = _incident(
        repository,
        node="zwave-01",
        service="zwave-js",
        capability="node.health",
    )
    assert incident is not None
    dispatched: list[dict[str, object]] = []
    job_id = UUID("22222222-2222-4222-8222-222222222222")

    def dispatch(payload):
        dispatched.append(payload)
        return SimpleNamespace(job_id=job_id)

    service = TsunadeExpertiseService(
        incidents=repository,
        investigations=FakeInvestigations(),  # type: ignore[arg-type]
        ai_dispatcher=dispatch,
    )
    try:
        outcome = service.diagnose(
            incident.incident_id,
            log_result={
                "sources": [
                    {
                        "source": "zwave-01",
                        "findings": [
                            {
                                "source": "zwave-01",
                                "signature": "node <value> transmission failed",
                                "category": "zwave",
                                "severity": "error",
                                "occurrences": 47,
                                "trend": "increasing",
                            }
                        ],
                    }
                ]
            },
        )
        updated = repository.get(incident.incident_id)
    finally:
        repository.close()

    assert outcome.status == "AI_QUEUED"
    assert outcome.ai_job_id == job_id
    parameters = dispatched[0]["parameters"]
    assert parameters["incident_id"] == str(incident.incident_id)
    sources = {entry["source"] for entry in parameters["evidence"]}
    assert sources == {
        "architecture.concerned",
        "shikamaru.observation",
        "history.relevant",
        "logs.analysis",
    }
    assert "topology" not in str(parameters).casefold()

    diagnostic = updated.events[-1]
    assert diagnostic.payload["cycle_status"] == "ai_queued"
    assert diagnostic.payload["decision"] == "investigate"
    assert diagnostic.payload["decision_source"] == "deterministic"
    assert diagnostic.payload["confidence"] == 0.90


def test_ai_hypotheses_remain_non_authoritative_when_tsunade_decides(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    incident = _incident(
        repository,
        node="zwave-01",
        service="zwave-js",
        capability="node.health",
    )
    assert incident is not None
    service = TsunadeExpertiseService(
        incidents=repository,
        investigations=FakeInvestigations(),  # type: ignore[arg-type]
    )
    try:
        service.record_ai_result(
            incident.incident_id,
            uuid4(),
            {
                "analysis_version": 2,
                "verdict": "KO",
                "generated_at": "2026-08-24T12:05:00Z",
                "model_id": "local-model",
                "model_sha256": "f" * 64,
                "interpretation": "Communication dégradée avec le nœud ciblé.",
                "summary": "Une hypothèse principale nécessite confirmation.",
                "findings": [
                    {
                        "code": "ZWAVE.TRANSMISSION",
                        "evidence": "47 occurrences groupées sur 24 h",
                        "confidence": 1,
                    }
                ],
                "hypotheses": [
                    {
                        "statement": (
                            "Les templates Home Assistant utilisent float "
                            "sans valeur par défaut."
                        ),
                        "confidence": 0.87,
                        "possible_causes": ["template Home Assistant incomplet"],
                        "supporting_evidence": ["float got invalid input 'unknown'"],
                        "contradicting_evidence": ["autres capteurs normaux"],
                    }
                ],
                "missing_context": ["configuration des templates"],
                "recommended_investigation": [
                    "Vérifier les templates Home Assistant qui utilisent float "
                    "sans valeur par défaut."
                ],
                "metrics": {
                    "prompt_tokens": 100,
                    "completion_tokens": 80,
                    "ttft_ms": 100,
                    "tokens_per_second": 70,
                    "duration_seconds": 2,
                },
            },
            evidence=[
                {
                    "source": "logs.analysis",
                    "content": (
                        "TemplateError float got invalid input unavailable for "
                        "sensor.teleinfo_041964385922_easf02 while processing "
                        "sensor.linky_bleue_hp"
                    ),
                }
            ],
        )
        updated = repository.get(incident.incident_id)
    finally:
        repository.close()

    assert updated.final_result is None

    diagnostic = updated.events[-2]
    proposal = updated.events[-1]

    assert diagnostic.payload["epistemic_status"] == "hypothesis"
    assert diagnostic.payload["analysis_version"] == 2

    assert diagnostic.payload["decision"] == "investigate"
    assert diagnostic.payload["decision_source"] == "katsuyu_ai"
    assert diagnostic.payload["confidence"] == 0.85

    assert diagnostic.payload["recommended_action"] == (
        "Vérifier les templates Home Assistant qui utilisent float "
        "sans valeur par défaut."
    )
    assert diagnostic.payload["investigation_commands"] == [
        {
            "title": "Vérifier les entités citées par le journal",
            "target": "Home Assistant > Outils de développement > Modèle",
            "safety": "Lecture seule",
            "expected": (
                "Affiche toujours le nom et l’état courant de chaque entité "
                "explicitement citée par le journal Home Assistant."
            ),
            "command": diagnostic.payload["investigation_commands"][0]["command"],
        }
    ]
    command = diagnostic.payload["investigation_commands"][0]["command"]
    assert "'sensor.teleinfo_041964385922_easf02'" in command
    assert "'sensor.linky_bleue_hp'" in command
    assert "{% for entity_id in entity_ids %}" in command
    assert "{{ states(entity_id) }}" in command

    assert proposal.payload["authorized"] is False
    assert (
        proposal.payload["investigation_commands"]
        == (diagnostic.payload["investigation_commands"])
    )
