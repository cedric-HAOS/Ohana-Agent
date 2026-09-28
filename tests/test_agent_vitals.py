"""Phase 5: last useful activity of the Agent's own components."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from aiohttp import web

from ohana_agent.core.http_listener import ThreadedHTTPListener
from ohana_agent.observation.exporters.durable_vision_client import (
    DurableVisionClient,
)
from ohana_agent.observation.exporters.vision_client_error import VisionClientError
from ohana_agent.plugins.mqtt.host_health import HostHealthMonitor, HostMetrics
from ohana_agent.runtime.administration_bootstrap import TsunadeObservationHandler
from ohana_agent.runtime.vitals import AgentVitals, stale_components
from ohana_agent.tsunade.expertise import TsunadeExpertiseService
from ohana_agent.tsunade.investigations import InvestigationResult, probe_failed

PARIS = ZoneInfo("Europe/Paris")


class Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


def make_vitals(clock: Clock) -> AgentVitals:
    return AgentVitals(
        monotonic_clock=clock,
        wall_clock=lambda: datetime(2026, 9, 28, 16, 30, tzinfo=PARIS),
    )


def test_component_waits_then_goes_stale_without_a_first_beat() -> None:
    clock = Clock()
    vitals = make_vitals(clock)
    vitals.declare("scheduler", label="Planificateur", max_silence_seconds=300)

    assert vitals.snapshot()[0]["state"] == "waiting"
    clock.value += 301
    (component,) = vitals.snapshot()

    assert component["state"] == "stale"
    assert component["last_activity_at"] is None
    assert component["silence_seconds"] is None


def test_beat_keeps_a_component_active_until_its_bound() -> None:
    clock = Clock()
    vitals = make_vitals(clock)
    vitals.declare("tsunade", label="Tsunade", max_silence_seconds=60)
    vitals.declare("scheduler", label="Planificateur", max_silence_seconds=300)

    clock.value += 50
    vitals.beat("tsunade")
    vitals.beat("scheduler")
    vitals.beat("undeclared")
    clock.value += 60
    snapshot = vitals.snapshot()

    assert [item["state"] for item in snapshot] == ["active", "active"]
    assert snapshot[0]["last_activity_at"] == "2026-09-28T16:30:00+02:00"
    assert snapshot[0]["silence_seconds"] == 60
    clock.value += 1
    assert stale_components(vitals.snapshot()) == ("tsunade",)


class FakeProbe:
    def collect(self) -> HostMetrics:
        return HostMetrics(
            hostname="infra-01",
            operating_system="Linux",
            kernel="6.12",
            cpu_count=4,
            cpu_percent=10.0,
            load_1m_per_cpu=0.2,
            memory_percent=40.0,
            memory_total_bytes=2_000_000,
            memory_available_bytes=1_000_000,
            swap_percent=0.0,
            swap_total_bytes=1_000_000,
            swap_used_bytes=0,
            disk_percent=30.0,
            disk_free_bytes=10_000_000,
            temperature_c=50.0,
            host_uptime_seconds=3600,
            agent_uptime_seconds=600,
            agent_restarts=0,
            failed_systemd_units=(),
            inactive_systemd_units=(),
        )


def test_host_health_degrades_immediately_on_a_stale_component() -> None:
    clock = Clock()
    vitals = make_vitals(clock)
    vitals.declare("administration", label="API", max_silence_seconds=60)
    vitals.beat("administration")
    monitor = HostHealthMonitor(FakeProbe(), vitals=vitals)

    healthy = monitor.collect()
    clock.value += 61
    stale = monitor.collect()
    vitals.beat("administration")
    recovered = monitor.collect()

    assert healthy.state == "healthy"
    assert healthy.to_dict()["agent_components"][0]["state"] == "active"
    assert stale.state == "degraded"
    assert stale.reasons == ("agent_components_stale",)
    assert stale.stale_agent_components == ("administration",)
    assert recovered.state == "healthy"


def test_host_health_without_vitals_keeps_its_former_payload() -> None:
    snapshot = HostHealthMonitor(FakeProbe()).collect()

    assert snapshot.agent_components == ()
    assert snapshot.stale_agent_components == ()


class FakeOutbox:
    def __init__(self) -> None:
        self.entries: list[SimpleNamespace] = []
        self.pending_count = 0

    def enqueue_many(self, payloads) -> None:
        self.entries += [
            SimpleNamespace(observation_id=p["observation_id"], payload=p)
            for p in payloads
        ]

    def oldest(self):
        return self.entries[0] if self.entries else None

    def mark_delivered(self, _observation_id) -> None:
        self.entries.pop(0)

    def mark_failed(self, _observation_id, _error) -> None:
        pass

    def close(self) -> None:
        pass


class FakeVision:
    def __init__(self) -> None:
        self.available = True

    def send_observation(self, _payload) -> None:
        if not self.available:
            raise VisionClientError("Timed out")


def test_delivery_beats_only_when_it_progresses() -> None:
    beats: list[int] = []
    vision = FakeVision()
    client = DurableVisionClient(
        vision, FakeOutbox(), on_progress=lambda: beats.append(1)
    )

    client.flush()  # empty backlog: nothing is late
    client.send_observation({"observation_id": "a"})
    client.flush()
    vision.available = False
    client.send_observation({"observation_id": "b"})
    client.flush()  # blocked, backlog kept

    assert len(beats) == 2


def test_tsunade_handler_beats_after_each_processed_observation() -> None:
    beats: list[int] = []
    handler = TsunadeObservationHandler(
        incidents=SimpleNamespace(process=lambda _observation: None),
        expertise=SimpleNamespace(),
        administration=SimpleNamespace(),
        logs_config=SimpleNamespace(enabled=False, sources=[]),
        notifications=None,
        on_processed=lambda: beats.append(1),
    )

    handler(SimpleNamespace(observation=object()))

    assert beats == [1]


class EmptyListener(ThreadedHTTPListener):
    heartbeat_seconds = 0.01

    def build_application(self) -> web.Application:
        return web.Application()


def test_listener_loop_beats_while_it_runs() -> None:
    beats: list[float] = []
    listener = EmptyListener(host="127.0.0.1", port=0, logger=logging.getLogger())
    listener.heartbeat = lambda: beats.append(time.monotonic())
    listener.start()
    try:
        deadline = time.monotonic() + 5
        while len(beats) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        listener.stop()

    assert len(beats) >= 3


def test_stale_component_selects_the_deterministic_vitals_procedure() -> None:
    incident = SimpleNamespace(
        service_id="ohana-host",
        capability_id="host.health",
        message="memory_degraded, agent_components_stale",
    )

    procedure = TsunadeExpertiseService._known_procedure(incident)

    assert procedure is not None
    assert procedure.operations == ("agent.vitals",)


def test_vitals_investigation_fails_only_with_a_stale_component() -> None:
    now = datetime(2026, 9, 28, 16, 30, tzinfo=PARIS)
    result = InvestigationResult(
        investigation_id=uuid4(),
        operation="agent.vitals",
        status="OK",
        started_at=now,
        finished_at=now,
        duration_seconds=0,
        result={"agent_components": [], "stale_agent_components": ["tsunade"]},
    )

    healthy = result.model_copy(
        update={"result": {"agent_components": [], "stale_agent_components": []}}
    )

    assert probe_failed(result)
    assert not probe_failed(healthy)
