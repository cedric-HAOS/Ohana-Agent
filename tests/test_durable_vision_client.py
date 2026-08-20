"""Tests for durable delivery to Ohana-Vision."""

from pathlib import Path
from threading import Event
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from observer.exporters import (
    DurableVisionClient,
    VisionClientError,
    VisionObservationOutbox,
)


class FakeVisionClient:
    def __init__(self) -> None:
        self.available = True
        self.observations: list[dict[str, Any]] = []
        self.infrastructure: list[dict[str, Any]] = []

    def send_observation(self, payload: dict[str, Any]) -> None:
        if not self.available:
            raise VisionClientError("Vision unavailable")
        self.observations.append(payload)

    def send_infrastructure(self, payload: dict[str, Any]) -> None:
        if not self.available:
            raise VisionClientError("Vision unavailable")
        self.infrastructure.append(payload)


def payload() -> dict[str, object]:
    return {
        "observation_id": str(uuid4()),
        "capability_id": "dns.resolve",
        "service_id": "dns-primary",
        "node_id": "infra-01",
        "status": "healthy",
        "observed_at": "2026-08-10T10:00:00+00:00",
        "metadata": {},
    }


def durable_client(tmp_path: Path, client: FakeVisionClient) -> DurableVisionClient:
    return DurableVisionClient(
        client,
        VisionObservationOutbox(tmp_path / "outbox.db"),
        retry_seconds=0.01,
    )


def test_client_delivers_and_removes_observation_in_background(tmp_path: Path) -> None:
    target = FakeVisionClient()
    client = durable_client(tmp_path, target)
    observation = payload()

    client.start()
    client.send_observation(observation)
    deadline = monotonic() + 1.0
    while client.pending_count and monotonic() < deadline:
        sleep(0.01)

    assert target.observations == [observation]
    assert client.pending_count == 0
    client.stop()


def test_slow_replay_never_blocks_new_observation_producers(tmp_path: Path) -> None:
    """A long backlog must not suspend Agent's scheduler and host-health loop."""

    class BlockingVisionClient(FakeVisionClient):
        def __init__(self) -> None:
            super().__init__()
            self.started = Event()
            self.release = Event()

        def send_observation(self, observation: dict[str, Any]) -> None:
            self.started.set()
            self.release.wait(timeout=1)
            super().send_observation(observation)

    target = BlockingVisionClient()
    client = durable_client(tmp_path, target)
    client.start()
    client.send_observation(payload())
    assert target.started.wait(timeout=1)

    started = monotonic()
    client.send_observation(payload())
    elapsed = monotonic() - started

    assert elapsed < 0.1
    assert client.pending_count == 2
    target.release.set()
    deadline = monotonic() + 1.0
    while client.pending_count and monotonic() < deadline:
        sleep(0.01)
    assert client.pending_count == 0
    client.stop()


def test_client_keeps_observation_when_vision_is_unavailable(tmp_path: Path) -> None:
    target = FakeVisionClient()
    target.available = False
    client = durable_client(tmp_path, target)

    client.send_observation(payload())

    assert client.pending_count == 1
    client.stop()


def test_background_worker_replays_observation_after_recovery(tmp_path: Path) -> None:
    target = FakeVisionClient()
    target.available = False
    client = durable_client(tmp_path, target)
    observation = payload()
    client.send_observation(observation)
    target.available = True

    client.start()
    deadline = monotonic() + 1.0
    while client.pending_count and monotonic() < deadline:
        sleep(0.01)

    assert client.pending_count == 0
    assert target.observations == [observation]
    client.stop()


def test_client_synchronizes_infrastructure_directly(tmp_path: Path) -> None:
    target = FakeVisionClient()
    client = durable_client(tmp_path, target)
    infrastructure = {"schema_version": "1.0"}

    client.send_infrastructure(infrastructure)

    assert target.infrastructure == [infrastructure]
    client.stop()
