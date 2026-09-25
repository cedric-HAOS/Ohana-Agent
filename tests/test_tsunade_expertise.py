"""Tests for Tsunade's deterministic-first, optional-AI expertise cycle."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.expertise import (
    TsunadeExpertiseService,
)
from ohana_agent.tsunade.incident_summary import incident_assessment
from ohana_agent.tsunade.incidents import (
    TsunadeIncidentRepository,
)
from ohana_agent.tsunade.investigations import InvestigationResult


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


def _teleinformation_observation(
    *,
    timestamp: datetime,
    age_seconds: int,
    maximum_age_seconds: int = 30,
) -> Observation:
    return Observation(
        node="linky-01",
        service="tic-linky",
        capability="teleinformation.freshness",
        status=ObservationStatus.UNHEALTHY,
        success=False,
        message=(f"Aucune trame téléinformation reçue depuis {age_seconds} secondes."),
        source="teleinformation.freshness",
        id=uuid4(),
        timestamp=timestamp,
        metadata={
            "device_id": "linky-01",
            "mode": "direct_http",
            "source_id": "rpi-linky",
            "meter_id": "041964385922",
            "maximum_age_seconds": maximum_age_seconds,
            "age_seconds": age_seconds,
        },
    )


class TeleinformationInvestigations(FakeInvestigations):
    def __init__(self, addon_state: str = "stopped") -> None:
        super().__init__()
        self.addon_state = addon_state
        self.snapshot_nodes: list[str] = []

    def read_only_snapshot(self, node_id: str) -> dict:
        self.snapshot_nodes.append(node_id)

        return {
            "configuration_inspection": {
                "remote": {
                    "origin": "linky-01 / Supervisor",
                    "addons": [
                        {
                            "addon": "6fc079ce_teleinfo2mqtt_ohana",
                            "state": self.addon_state,
                        }
                    ],
                }
            }
        }


@pytest.mark.parametrize("probe_status", ["KO", "TIMEOUT"])
@pytest.mark.parametrize("service_name", ["memory", "dns", "mqtt", "systemd"])
def test_unavailable_probe_never_confirms_target_failure(
    tmp_path, probe_status, service_name
):
    database = tmp_path / "control.db"
    repository = TsunadeIncidentRepository(database)
    incident = _incident(
        repository, service=service_name, capability=f"{service_name}.health"
    )

    class UnavailableInvestigations(FakeInvestigations):
        def execute(self, payload):
            result = super().execute(payload)
            return result.model_copy(
                update={"status": probe_status, "error": "Probe unavailable"}
            )

    investigations = UnavailableInvestigations()
    service = TsunadeExpertiseService(
        incidents=repository, investigations=investigations
    )
    try:
        outcome = service.diagnose(incident.incident_id)
    finally:
        repository.close()
    assert outcome.status == "INSUFFICIENT_CONTEXT"
    assert outcome.decision == "watch"
    assert investigations.operations

    # The same conclusion must survive restart and reach both UI projections.
    repository = TsunadeIncidentRepository(database)
    try:
        for updated in (repository.get(incident.incident_id), repository.list()[0]):
            assessment = incident_assessment(updated)
            assert updated.state == "active"
            assert updated.expertise_state == "insufficient_context"
            assert assessment["conclusion"] == outcome.diagnosis
            assert assessment["reason"]
            assert assessment["recommended_action"]
            assert assessment["decision"] == "watch"

            assert assessment["diagnostic_level"] == "INSUFFICIENT_CONTEXT"
            assert assessment["confirmation_gap"]
        assert not any(
            e.payload.get("epistemic_status") == "confirmed_by_probe"
            for e in repository.get(incident.incident_id).events
        )
    finally:
        repository.close()


def test_disabled_backup_is_not_a_confirmed_backup_failure(tmp_path):
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    incident = _incident(repository, service="backup", capability="backup.health")
    service = TsunadeExpertiseService(
        incidents=repository,
        investigations=FakeInvestigations({"enabled": False, "status": "disabled"}),
    )
    try:
        assert service.diagnose(incident.incident_id).status == "INSUFFICIENT_CONTEXT"
    finally:
        repository.close()


@pytest.mark.parametrize(
    ("service_name", "measurement"),
    [
        ("dns", {"success": False}),
        ("mqtt", {"success": False}),
        ("memory", {"memory_percent": 95}),
        ("cpu", {"cpu_percent": 99}),
        ("disk", {"disk_percent": 95}),
        ("systemd", {"failed_systemd_units": ["example.service"]}),
        ("backup", {"enabled": False, "status": "FAILED"}),
    ],
)
def test_confirmed_fault_and_healthy_recovery_without_katsuyu(
    tmp_path, service_name, measurement
):
    database = tmp_path / "control.db"
    repository = TsunadeIncidentRepository(database)
    incident = _incident(
        repository, service=service_name, capability=f"{service_name}.health"
    )
    service = TsunadeExpertiseService(
        incidents=repository, investigations=FakeInvestigations(measurement)
    )
    try:
        outcome = service.diagnose(incident.incident_id)
        assert outcome.status == "DETERMINISTIC"
        assert outcome.ai_job_id is None
        assert outcome.decision == "action_required"
        assert repository.get(incident.incident_id).state == "active"
    finally:
        repository.close()
    repository = TsunadeIncidentRepository(database)
    try:
        assert (
            incident_assessment(repository.get(incident.incident_id))["state"]
            == "action_required"
        )
        recovered = repository.process(
            Observation(
                node="infra-01",
                service=service_name,
                capability=f"{service_name}.health",
                status=ObservationStatus.HEALTHY,
                success=True,
                message="Healthy again",
                source=f"{service_name}.health",
                id=uuid4(),
                timestamp=incident.last_observed_at + timedelta(minutes=5),
                metadata={"device_id": "infra-01"},
            )
        )
        assert recovered.incident_id == incident.incident_id
        assert recovered.state == "resolved"
        assert incident_assessment(recovered)["state"] == "resolved"
    finally:
        repository.close()


def test_unavailable_probe_can_use_optional_ai_without_confirming_failure(tmp_path):
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    incident = _incident(repository, service="memory", capability="memory.health")
    dispatched = []

    class UnavailableInvestigations(FakeInvestigations):
        def execute(self, payload):
            return super().execute(payload).model_copy(update={"status": "TIMEOUT"})

    def dispatch(payload):
        dispatched.append(payload)
        return SimpleNamespace(job_id=uuid4())

    service = TsunadeExpertiseService(
        incidents=repository,
        investigations=UnavailableInvestigations(),
        ai_dispatcher=dispatch,
    )
    try:
        assert service.diagnose(incident.incident_id).status == "AI_QUEUED"
        assert len(dispatched) == 1
        evidence = dispatched[0]["parameters"]["evidence"]
        assert any(
            item["source"] == "investigations.deterministic"
            and "TIMEOUT" in item["content"]
            for item in evidence
        )
        assert repository.get(incident.incident_id).state == "active"
    finally:
        repository.close()


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

    diagnostic = updated.events[-2]

    assert diagnostic.payload["epistemic_status"] == "confirmed_by_probe"
    assert diagnostic.payload["diagnostic_level"] == "CONFIRMED"
    assert diagnostic.payload["confirmation_gap"] == []

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
    assert parameters["max_output_tokens"] == 8_192
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


def test_operator_requested_log_diagnosis_bypasses_watch_decision(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    incident = _incident(
        repository,
        node="ha-01",
        service="home-assistant",
        capability="logs.health",
    )
    assert incident is not None
    dispatched: list[dict[str, object]] = []
    job_id = UUID("22222222-2222-4222-8222-222222222222")
    log_result = {
        "sources": [
            {
                "source": "ha-01",
                "findings": [
                    {
                        "source": "ha-01",
                        "signature": "template float unavailable",
                        "category": "home_assistant",
                        "severity": "error",
                        "occurrences": 17,
                        "reference_occurrences": 10,
                        "trend": "increasing",
                    }
                ],
            }
        ]
    }

    def dispatch(payload):
        dispatched.append(payload)
        return SimpleNamespace(job_id=job_id)

    service = TsunadeExpertiseService(
        incidents=repository,
        investigations=FakeInvestigations(),  # type: ignore[arg-type]
        ai_dispatcher=dispatch,
    )
    try:
        automatic = service.diagnose(incident.incident_id, log_result=log_result)
        requested = service.diagnose(
            incident.incident_id,
            log_result=log_result,
            operator_requested=True,
        )
        updated = repository.get(incident.incident_id)
    finally:
        repository.close()

    assert automatic.status == "DETERMINISTIC"
    assert automatic.decision == "watch"
    assert requested.status == "AI_QUEUED"
    assert requested.ai_job_id == job_id
    assert len(dispatched) == 1
    assert updated.events[-1].payload["cycle_status"] == "ai_queued"
    assert updated.events[-1].payload["trigger"] == "operator_request"


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

    assert diagnostic.payload["diagnostic_level"] == "PROBABLE"
    assert diagnostic.payload["confirmation_gap"] == ["configuration des templates"]

    assert diagnostic.payload["confidence"] == 0.85

    assessment = incident_assessment(updated)

    assert assessment["diagnostic_level"] == "PROBABLE"
    assert assessment["confirmation_gap"] == ["configuration des templates"]

    assert assessment["decision"] != "action_required"
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


def test_ai_evidence_redacts_nested_credentials() -> None:
    content = TsunadeExpertiseService._bounded_json(  # noqa: SLF001
        {
            "status": "FAILED",
            "password": "fake-password",
            "details": {
                "endpoint": (
                    "https://operator:fictional-password@example.test/check"
                    "?api_key=fake-api-key"
                ),
                "authorization": ("Bearer fake-bearer-token"),
            },
        }
    )

    for secret in (
        "fake-password",
        "fictional-password",
        "fake-api-key",
        "fake-bearer-token",
    ):
        assert secret not in content

    assert "example.test/check" in content
    assert "[redacted]" in content


def test_ai_result_is_redacted_before_persistence(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")

    incident = _incident(
        repository,
        node="zwave-01",
        service="zwave-js",
        capability="node.health",
    )

    service = TsunadeExpertiseService(
        incidents=repository,
        investigations=FakeInvestigations(),
    )

    try:
        service.record_ai_result(
            incident.incident_id,
            uuid4(),
            {
                "analysis_version": 2,
                "verdict": "KO",
                "generated_at": ("2026-09-21T16:00:00Z"),
                "model_id": "local-model",
                "model_sha256": "f" * 64,
                "interpretation": ("token=fake-ai-token"),
                "summary": ("password=fake-ai-password"),
                "findings": [
                    {
                        "code": "TEST.SENSITIVE_EVIDENCE",
                        "evidence": ("Authorization: Bearer fake-finding-token"),
                        "confidence": 0.90,
                    }
                ],
                "hypotheses": [
                    {
                        "statement": (
                            "Une cause possible implique token=fake-hypothesis-token"
                        ),
                        "confidence": 0.70,
                        "possible_causes": ["password=fake-hypothesis-password"],
                        "supporting_evidence": [
                            "Authorization: Bearer fake-hypothesis-bearer"
                        ],
                        "contradicting_evidence": [],
                    }
                ],
                "missing_context": [],
                "recommended_investigation": [],
                "metrics": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "ttft_ms": 10,
                    "tokens_per_second": 10,
                    "duration_seconds": 1,
                },
            },
        )

        rendered = repository.get(incident.incident_id).model_dump_json()

        assert "fake-ai-token" not in rendered
        assert "fake-ai-password" not in rendered
        assert "[redacted]" in rendered
        for secret in (
            "fake-ai-token",
            "fake-ai-password",
            "fake-finding-token",
            "fake-hypothesis-token",
            "fake-hypothesis-password",
            "fake-hypothesis-bearer",
        ):
            assert secret not in rendered
    finally:
        repository.close()


def test_teleinformation_stopped_addon_is_confirmed_before_ai(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")

    incident = repository.process(
        _teleinformation_observation(
            timestamp=datetime(2026, 9, 21, 18, 41, tzinfo=UTC),
            age_seconds=96,
        )
    )
    assert incident is not None

    investigations = TeleinformationInvestigations()
    dispatched: list[dict[str, object]] = []

    def dispatch(payload):
        dispatched.append(payload)
        return SimpleNamespace(job_id=uuid4())

    service = TsunadeExpertiseService(
        incidents=repository,
        investigations=investigations,  # type: ignore[arg-type]
        ai_dispatcher=dispatch,
    )

    try:
        outcome = service.diagnose(incident.incident_id)
        updated = repository.get(incident.incident_id)
    finally:
        repository.close()

    assert outcome.status == "DETERMINISTIC"
    assert outcome.ai_job_id is None
    assert outcome.decision == "investigate"
    assert outcome.decision_source == "deterministic"

    # Supervisor must have been inspected on the incident's actual node.
    assert investigations.snapshot_nodes == ["linky-01"]

    # A deterministic proof must prevent any Katsuyu escalation.
    assert dispatched == []

    decision = updated.latest_decision
    assert decision is not None
    assert decision["epistemic_status"] == "confirmed_by_supervisor"
    assert decision["diagnostic_level"] == "CONFIRMED"
    assert decision["confirmation_gap"] == []
    assert decision["decision_source"] == "deterministic"
    assert decision["confidence"] == 1.0
    assert decision["basis_fingerprint"]
    assert "stopped" in decision["reason"].casefold()
    assert "teleinfo2mqtt" in decision["conclusion"].casefold()


def test_identical_teleinformation_observation_keeps_diagnosis_current(
    tmp_path: Path,
) -> None:
    repository = TsunadeIncidentRepository(tmp_path / "control.db")

    started_at = datetime(2026, 9, 21, 18, 41, tzinfo=UTC)

    incident = repository.process(
        _teleinformation_observation(
            timestamp=started_at,
            age_seconds=96,
        )
    )
    assert incident is not None

    investigations = TeleinformationInvestigations()

    service = TsunadeExpertiseService(
        incidents=repository,
        investigations=investigations,  # type: ignore[arg-type]
    )

    try:
        outcome = service.diagnose(incident.incident_id)
        assert outcome.status == "DETERMINISTIC"

        diagnosed = repository.get(incident.incident_id)
        before = incident_assessment(diagnosed)

        assert before["decision_current"] is True

        # Shikamaru observes the same fault one minute later.
        # Only the duration/message changed.
        repeated = repository.process(
            _teleinformation_observation(
                timestamp=started_at + timedelta(minutes=1),
                age_seconds=156,
            )
        )
        assert repeated is not None

        after = incident_assessment(repository.get(incident.incident_id))

        assert repeated.occurrence_count == 2

        # The passage of time alone is not new diagnostic evidence.
        assert after["decision_current"] is True
        assert after["state"] == "investigate"
        assert after["label"] == "À approfondir"

        # A material change in the monitored contract MUST invalidate
        # the previous diagnostic basis.
        changed = repository.process(
            _teleinformation_observation(
                timestamp=started_at + timedelta(minutes=2),
                age_seconds=216,
                maximum_age_seconds=60,
            )
        )
        assert changed is not None

        changed_assessment = incident_assessment(repository.get(incident.incident_id))

        assert changed_assessment["decision_current"] is False
        assert changed_assessment["state"] == "stale"
        assert changed_assessment["label"] == "Analyse à actualiser"

    finally:
        repository.close()
