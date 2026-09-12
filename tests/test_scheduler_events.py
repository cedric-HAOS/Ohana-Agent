from datetime import UTC, datetime

from ohana_agent.scheduler import (
    FakeClock,
    ScheduledTaskExecuted,
    ScheduledTaskFailed,
    ScheduledTaskTriggered,
    Scheduler,
    SchedulerEvent,
    SchedulerStarted,
    SchedulerStopped,
    SchedulerTicked,
    Task,
)
from ohana_agent.scheduler.oneshot_trigger import OneShotTrigger
from ohana_agent.scheduler.task_executor import FailingTaskExecutor


class FakeEventBus:
    """Fake event bus for scheduler tests."""

    def __init__(self) -> None:
        self.published_events: list[object] = []

    def publish(self, event: object) -> None:
        """Store published events."""
        self.published_events.append(event)


def test_scheduler_event_has_id_and_timestamp() -> None:
    event = SchedulerEvent()

    assert event.event_id
    assert event.occurred_at is not None


def test_scheduler_started_is_scheduler_event() -> None:
    event = SchedulerStarted()

    assert isinstance(event, SchedulerEvent)


def test_scheduler_stopped_is_scheduler_event() -> None:
    event = SchedulerStopped()

    assert isinstance(event, SchedulerEvent)


def test_scheduler_ticked_is_scheduler_event() -> None:
    event = SchedulerTicked()

    assert isinstance(event, SchedulerEvent)


def test_scheduled_task_triggered_contains_task_payload() -> None:
    event = ScheduledTaskTriggered(
        task_name="backup",
        command="system.backup",
        arguments={"target": "nas"},
    )

    assert event.task_name == "backup"
    assert event.command == "system.backup"
    assert event.arguments == {"target": "nas"}


def test_scheduled_task_executed_contains_result() -> None:
    event = ScheduledTaskExecuted(
        task_name="backup",
        command="system.backup",
        arguments={"target": "nas"},
        result={"status": "ok"},
    )

    assert event.task_name == "backup"
    assert event.command == "system.backup"
    assert event.arguments == {"target": "nas"}
    assert event.result == {"status": "ok"}


def test_scheduled_task_failed_contains_error() -> None:
    event = ScheduledTaskFailed(
        task_name="backup",
        command="system.backup",
        arguments={"target": "nas"},
        error="disk unavailable",
    )

    assert event.task_name == "backup"
    assert event.command == "system.backup"
    assert event.arguments == {"target": "nas"}
    assert event.error == "disk unavailable"


def test_scheduler_publishes_started_event() -> None:
    event_bus = FakeEventBus()
    scheduler = Scheduler(event_bus=event_bus)

    scheduler.start()

    assert len(event_bus.published_events) == 1
    assert isinstance(event_bus.published_events[0], SchedulerStarted)


def test_scheduler_publishes_stopped_event() -> None:
    event_bus = FakeEventBus()
    scheduler = Scheduler(event_bus=event_bus)

    scheduler.stop()

    assert len(event_bus.published_events) == 1
    assert isinstance(event_bus.published_events[0], SchedulerStopped)


def test_scheduler_publishes_ticked_event() -> None:
    event_bus = FakeEventBus()
    scheduler = Scheduler(event_bus=event_bus)

    scheduler.start()
    scheduler.tick()

    assert len(event_bus.published_events) == 2
    assert isinstance(event_bus.published_events[0], SchedulerStarted)
    assert isinstance(event_bus.published_events[1], SchedulerTicked)


def test_scheduler_publishes_task_triggered_event() -> None:
    event_bus = FakeEventBus()
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock = FakeClock(now)
    scheduler = Scheduler(clock=clock, event_bus=event_bus)
    task = Task(
        name="Backup",
        command="system.backup",
        arguments={"target": "nas"},
        trigger=OneShotTrigger(now),
    )

    scheduler.add_task(task)
    scheduler.start()

    scheduler.tick()

    assert any(
        isinstance(event, ScheduledTaskTriggered)
        for event in event_bus.published_events
    )


def test_scheduler_publishes_task_executed_event() -> None:
    event_bus = FakeEventBus()
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock = FakeClock(now)
    scheduler = Scheduler(clock=clock, event_bus=event_bus)
    task = Task(
        name="Backup",
        command="system.backup",
        arguments={"target": "nas"},
        trigger=OneShotTrigger(now),
    )

    scheduler.add_task(task)
    scheduler.start()

    scheduler.tick()

    assert any(
        isinstance(event, ScheduledTaskExecuted) for event in event_bus.published_events
    )


def test_scheduler_publishes_task_failed_event() -> None:
    event_bus = FakeEventBus()
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock = FakeClock(now)
    scheduler = Scheduler(
        clock=clock,
        executor=FailingTaskExecutor(),
        event_bus=event_bus,
    )
    task = Task(
        name="Backup",
        command="system.backup",
        arguments={"target": "nas"},
        trigger=OneShotTrigger(now),
    )

    scheduler.add_task(task)
    scheduler.start()

    scheduler.tick()

    assert any(
        isinstance(event, ScheduledTaskFailed) for event in event_bus.published_events
    )
