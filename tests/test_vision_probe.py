"""Phase 5: the Agent watches Ohana-Vision without depending on it."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from urllib.error import URLError
from uuid import uuid4

from ohana_agent.plugins.mqtt.host_health import HostHealthMonitor
from ohana_agent.runtime.administration_bootstrap import incident_notification
from ohana_agent.runtime.vision_probe import (
    VisionVitalsProbe,
    vision_failures,
    vitals_url,
)
from ohana_agent.runtime.vitals import AgentVitals
from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from tests.test_agent_vitals import Clock, FakeProbe


def test_vitals_url_follows_the_configured_vision() -> None:
    assert (
        vitals_url("http://127.0.0.1:8000/api/observations")
        == "http://127.0.0.1:8000/api/runtime/vitals"
    )


def running(silence: int | None = 12) -> dict:
    return {
        "state": "running",
        "started_at": "2026-09-28T17:00:00+02:00",
        "last_ingested_at": "2026-09-28T17:10:00+02:00",
        "ingestion_silence_seconds": silence,
    }


def test_probe_records_availability_and_ingestion_silence() -> None:
    answers: list[object] = [running(12), URLError("refused"), running(301)]

    def fetch(_url: str, _timeout: float) -> dict:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    probe = VisionVitalsProbe("http://vision", fetch=fetch)

    assert probe.latest() is None
    assert vision_failures(probe.check_now()) == ()
    down = probe.check_now()
    assert down["available"] is False and down["error"] == "URLError"
    assert vision_failures(down) == ("vision_http_unavailable",)
    assert vision_failures(probe.check_now()) == ("vision_ingestion_stale",)
    assert probe.latest()["ingestion_silence_seconds"] == 301


def test_probe_forgets_a_measure_too_old_to_trust() -> None:
    clock = Clock()
    probe = VisionVitalsProbe(
        "http://vision",
        interval_seconds=60,
        fetch=lambda _url, _timeout: running(),
        monotonic_clock=clock,
    )
    probe.check_now()
    clock.value += 181

    assert probe.latest() is None


def test_invalid_json_shape_does_not_stop_the_probe() -> None:
    answers = iter([[], running()])
    probe = VisionVitalsProbe("http://vision", fetch=lambda *_: next(answers))

    assert probe.check_now()["error"] == "ValueError"
    assert probe.check_now()["available"] is True


def test_unreachable_vision_becomes_critical_after_three_samples() -> None:
    state = {"available": False, "ingestion_silence_seconds": None}
    clock = Clock()
    vitals = AgentVitals(monotonic_clock=clock)
    vitals.declare("vision_delivery", label="Livraison", max_silence_seconds=60)
    clock.value += 61  # never delivered: Vision is down
    monitor = HostHealthMonitor(FakeProbe(), vitals=vitals, vision=lambda: state)

    first = monitor.collect()
    monitor.collect()
    third = monitor.collect()

    # A deployment restart (one or two samples) opens nothing.
    assert first.state == "healthy"
    assert third.state == "critical"
    # The blocked delivery is Vision's failure, not an Agent component's.
    assert third.reasons == ("vision_http_unavailable",)
    assert third.stale_agent_components == ()
    assert third.vision == state


def test_silent_ingestion_is_degraded() -> None:
    monitor = HostHealthMonitor(
        FakeProbe(),
        required_samples=1,
        vision=lambda: {"available": True, "ingestion_silence_seconds": 900},
    )

    snapshot = monitor.collect()

    assert snapshot.state == "degraded"
    assert snapshot.reasons == ("vision_ingestion_stale",)


def test_unknown_vision_state_changes_nothing() -> None:
    snapshot = HostHealthMonitor(FakeProbe(), vision=lambda: None).collect()

    assert snapshot.state == "healthy"
    assert snapshot.vision is None


def test_vision_failure_selects_the_vision_procedure_first() -> None:
    incident = SimpleNamespace(
        service_id="ohana-host",
        capability_id="host.health",
        message="systemd_units_inactive, vision_http_unavailable",
    )

    procedure = TsunadeExpertiseService._known_procedure(incident)

    assert procedure is not None and procedure.operations == ("vision.status",)


def incident(**changes) -> SimpleNamespace:
    observation_id = uuid4()
    values = {
        "incident_id": uuid4(),
        "state": "active",
        "severity": "critical",
        "occurrence_count": 4,
        "message": "systemd_units_inactive, vision_http_unavailable",
        "started_at": datetime(2026, 9, 28, 17, 0),
        "last_observation_id": observation_id,
        "events": [
            SimpleNamespace(kind="opened", observation_id=uuid4()),
            SimpleNamespace(kind="escalated", observation_id=observation_id),
        ],
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_escalation_to_critical_pushes_once() -> None:
    escalated = incident()
    later = incident(events=[SimpleNamespace(kind="escalated", observation_id=uuid4())])

    notification = incident_notification(escalated)

    assert notification is not None and notification["type"] == "CRITICAL"
    assert incident_notification(later) is None
