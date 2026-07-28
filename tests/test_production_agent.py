from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from observer.exporters import VisionClientError
from production_agent import ProductionAgent
from scheduler import Scheduler


@dataclass
class FakeScheduler:
    """Capture scheduler lifecycle operations."""

    running: bool = False
    start_calls: int = 0
    stop_calls: int = 0
    tick_calls: int = 0

    def start(self) -> None:
        self.start_calls += 1
        self.running = True

    def stop(self) -> None:
        self.stop_calls += 1
        self.running = False

    def tick(self) -> list[object]:
        self.tick_calls += 1
        return []


@dataclass
class FakeVisionClient:
    """Return configured infrastructure synchronization outcomes."""

    outcomes: list[Exception | None] = field(default_factory=list)
    infrastructure_payloads: list[dict[str, Any]] = field(default_factory=list)

    def send_observation(
        self,
        payload: dict[str, Any],
    ) -> None:
        del payload

    def send_infrastructure(
        self,
        payload: dict[str, Any],
    ) -> None:
        self.infrastructure_payloads.append(payload)

        if not self.outcomes:
            return

        outcome = self.outcomes.pop(0)

        if outcome is not None:
            raise outcome


@dataclass
class FakeStopEvent:
    """Provide deterministic waits for ProductionAgent.run tests."""

    wait_results: list[bool]
    wait_timeouts: list[float] = field(default_factory=list)
    stopped: bool = False

    def clear(self) -> None:
        self.stopped = False

    def is_set(self) -> bool:
        return self.stopped

    def wait(self, timeout: float) -> bool:
        self.wait_timeouts.append(timeout)
        result = self.wait_results.pop(0)

        if result:
            self.stopped = True

        return result

    def set(self) -> None:
        self.stopped = True


@dataclass
class SequenceClock:
    """Return deterministic monotonic timestamps."""

    values: list[float]

    def __call__(self) -> float:
        return self.values.pop(0)


def test_production_agent_can_be_created() -> None:
    scheduler = Scheduler()
    agent = ProductionAgent(
        scheduler=scheduler,
    )

    assert agent.scheduler is scheduler
    assert agent.running is False
    assert agent.infrastructure_synchronized is False


def test_production_agent_starts_scheduler_without_vision_sync() -> None:
    scheduler = Scheduler()
    agent = ProductionAgent(
        scheduler=scheduler,
    )

    agent.start()

    assert scheduler.running is True
    assert agent.running is True
    assert agent.infrastructure_synchronized is True

    agent.stop()


def test_production_agent_synchronizes_before_starting_scheduler() -> None:
    scheduler = FakeScheduler()
    client = FakeVisionClient()
    payload = {
        "schema_version": 1,
    }
    agent = ProductionAgent(
        scheduler=scheduler,  # type: ignore[arg-type]
        vision_client=client,
        infrastructure_payload=payload,
    )

    agent.start()

    assert client.infrastructure_payloads == [payload]
    assert scheduler.start_calls == 1
    assert agent.infrastructure_synchronized is True
    assert agent.running is True

    agent.stop()


def test_production_agent_does_not_start_when_vision_is_unavailable() -> None:
    scheduler = FakeScheduler()
    client = FakeVisionClient(
        outcomes=[
            VisionClientError("Vision unavailable"),
        ]
    )
    agent = ProductionAgent(
        scheduler=scheduler,  # type: ignore[arg-type]
        vision_client=client,
        infrastructure_payload={"schema_version": 1},
    )

    agent.start()

    assert scheduler.start_calls == 0
    assert scheduler.tick_calls == 0
    assert agent.infrastructure_synchronized is False
    assert agent.running is False


def test_production_agent_retries_until_vision_accepts_snapshot() -> None:
    scheduler = FakeScheduler()
    client = FakeVisionClient(
        outcomes=[
            VisionClientError("Vision unavailable"),
            None,
        ]
    )
    stop_event = FakeStopEvent(
        wait_results=[
            False,
            True,
        ]
    )
    agent = ProductionAgent(
        scheduler=scheduler,  # type: ignore[arg-type]
        vision_client=client,
        infrastructure_payload={"schema_version": 1},
        tick_interval_seconds=1.0,
        infrastructure_retry_seconds=10.0,
    )
    agent._stop_event = stop_event  # type: ignore[assignment]

    agent.run()

    assert len(client.infrastructure_payloads) == 2
    assert stop_event.wait_timeouts == [
        10.0,
        1.0,
    ]
    assert scheduler.start_calls == 1
    assert scheduler.tick_calls == 0
    assert scheduler.stop_calls == 1


def test_production_agent_pauses_and_retries_after_refresh_failure() -> None:
    scheduler = FakeScheduler()
    client = FakeVisionClient(
        outcomes=[
            None,
            VisionClientError("Vision restarted"),
            None,
        ]
    )
    stop_event = FakeStopEvent(
        wait_results=[
            False,
            False,
            False,
            True,
        ]
    )
    clock = SequenceClock(
        values=[
            0.0,
            300.0,
            301.0,
            302.0,
        ]
    )
    agent = ProductionAgent(
        scheduler=scheduler,  # type: ignore[arg-type]
        vision_client=client,
        infrastructure_payload={"schema_version": 1},
        tick_interval_seconds=1.0,
        infrastructure_retry_seconds=10.0,
        infrastructure_refresh_seconds=300.0,
        monotonic_clock=clock,
    )
    agent._stop_event = stop_event  # type: ignore[assignment]

    agent.run()

    assert len(client.infrastructure_payloads) == 3
    assert stop_event.wait_timeouts == [
        1.0,
        10.0,
        1.0,
        1.0,
    ]
    assert scheduler.start_calls == 2
    assert scheduler.stop_calls == 2
    assert scheduler.tick_calls == 1


def test_production_agent_propagates_unexpected_sync_error() -> None:
    scheduler = FakeScheduler()
    client = FakeVisionClient(
        outcomes=[
            ValueError("invalid snapshot"),
        ]
    )
    agent = ProductionAgent(
        scheduler=scheduler,  # type: ignore[arg-type]
        vision_client=client,
        infrastructure_payload={"schema_version": 1},
    )

    with pytest.raises(
        ValueError,
        match="invalid snapshot",
    ):
        agent.start()

    assert scheduler.start_calls == 0


def test_production_agent_stops_scheduler() -> None:
    scheduler = Scheduler()
    agent = ProductionAgent(
        scheduler=scheduler,
    )
    agent.start()

    agent.stop()

    assert scheduler.running is False
    assert agent.running is False
    assert agent.infrastructure_synchronized is False


@pytest.mark.parametrize(
    ("field_name", "field_value", "message"),
    [
        (
            "tick_interval_seconds",
            0,
            "tick_interval_seconds must be greater than zero.",
        ),
        (
            "infrastructure_retry_seconds",
            0,
            "infrastructure_retry_seconds must be greater than zero.",
        ),
        (
            "infrastructure_refresh_seconds",
            0,
            "infrastructure_refresh_seconds must be greater than zero.",
        ),
    ],
)
def test_production_agent_rejects_invalid_intervals(
    field_name: str,
    field_value: float,
    message: str,
) -> None:
    arguments: dict[str, object] = {
        "scheduler": Scheduler(),
        field_name: field_value,
    }

    with pytest.raises(
        ValueError,
        match=message,
    ):
        ProductionAgent(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("vision_client", "infrastructure_payload"),
    [
        (FakeVisionClient(), None),
        (None, {"schema_version": 1}),
    ],
)
def test_production_agent_requires_client_and_payload_together(
    vision_client: FakeVisionClient | None,
    infrastructure_payload: dict[str, Any] | None,
) -> None:
    with pytest.raises(
        ValueError,
        match=("vision_client and infrastructure_payload must be configured together"),
    ):
        ProductionAgent(
            scheduler=Scheduler(),
            vision_client=vision_client,
            infrastructure_payload=infrastructure_payload,
        )


@dataclass
class FakeHomeAssistantPublisher:
    """Capture MQTT Home Assistant publisher lifecycle operations."""

    start_calls: int = 0
    tick_calls: int = 0
    stop_calls: int = 0

    def start(self) -> None:
        self.start_calls += 1

    def tick(self) -> None:
        self.tick_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


def test_production_agent_manages_home_assistant_publisher() -> None:
    scheduler = FakeScheduler()
    publisher = FakeHomeAssistantPublisher()
    agent = ProductionAgent(
        scheduler=scheduler,  # type: ignore[arg-type]
        home_assistant_publisher=publisher,
    )

    agent.start()
    agent.tick()
    agent.stop()

    assert publisher.start_calls == 1
    assert publisher.tick_calls == 1
    assert publisher.stop_calls == 1
