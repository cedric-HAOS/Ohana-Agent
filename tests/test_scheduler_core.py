from datetime import UTC, datetime, timedelta

import pytest

from ohana_agent.scheduler import (
    FakeClock,
    IntervalTrigger,
    OneShotTrigger,
    Scheduler,
    Task,
)
from ohana_agent.scheduler.task_executor import FailingTaskExecutor


def test_scheduler_is_stopped_by_default() -> None:
    scheduler = Scheduler()

    assert scheduler.running is False


def test_scheduler_can_start_and_stop() -> None:
    scheduler = Scheduler()

    scheduler.start()

    assert scheduler.running is True

    scheduler.stop()

    assert scheduler.running is False


def test_scheduler_can_add_and_get_task() -> None:
    scheduler = Scheduler()
    trigger = IntervalTrigger(timedelta(seconds=30))
    task = Task(command="health.check", trigger=trigger)

    scheduler.add_task(task)

    assert scheduler.get_task(task.id) == task


def test_scheduler_rejects_duplicate_task_id() -> None:
    scheduler = Scheduler()
    trigger = IntervalTrigger(timedelta(seconds=30))
    task = Task(command="health.check", trigger=trigger)

    scheduler.add_task(task)

    with pytest.raises(ValueError, match=f"task already exists: {task.id}"):
        scheduler.add_task(task)


def test_scheduler_remove_task() -> None:
    scheduler = Scheduler()
    trigger = IntervalTrigger(timedelta(seconds=30))
    task = Task(command="health.check", trigger=trigger)

    scheduler.add_task(task)

    removed = scheduler.remove_task(task.id)

    assert removed == task
    assert scheduler.list_tasks() == []


def test_scheduler_get_unknown_task_raises_key_error() -> None:
    scheduler = Scheduler()

    with pytest.raises(KeyError, match="task not found: missing"):
        scheduler.get_task("missing")


def test_scheduler_remove_unknown_task_raises_key_error() -> None:
    scheduler = Scheduler()

    with pytest.raises(KeyError, match="task not found: missing"):
        scheduler.remove_task("missing")


def test_scheduler_lists_tasks_by_priority() -> None:
    scheduler = Scheduler()

    low_priority = Task(
        command="backup.run",
        trigger=IntervalTrigger(timedelta(minutes=5)),
        priority=100,
    )
    high_priority = Task(
        command="health.check",
        trigger=IntervalTrigger(timedelta(minutes=5)),
        priority=10,
    )

    scheduler.add_task(low_priority)
    scheduler.add_task(high_priority)

    assert scheduler.list_tasks() == [high_priority, low_priority]


def test_scheduler_due_tasks_returns_only_due_tasks() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    scheduler = Scheduler(clock=FakeClock(now))

    due_task = Task(command="health.check", trigger=OneShotTrigger(now))
    later_task = Task(
        command="backup.run",
        trigger=OneShotTrigger(now + timedelta(minutes=5)),
    )

    scheduler.add_task(due_task)
    scheduler.add_task(later_task)

    assert scheduler.due_tasks() == [due_task]


def test_scheduler_due_tasks_ignores_disabled_tasks() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    scheduler = Scheduler(clock=FakeClock(now))

    task = Task(
        command="health.check",
        trigger=OneShotTrigger(now),
        enabled=False,
    )

    scheduler.add_task(task)

    assert scheduler.due_tasks() == []


def test_scheduler_due_tasks_are_sorted_by_priority() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    scheduler = Scheduler(clock=FakeClock(now))

    low_priority = Task(
        command="backup.run",
        trigger=OneShotTrigger(now),
        priority=100,
    )
    high_priority = Task(
        command="health.check",
        trigger=OneShotTrigger(now),
        priority=10,
    )

    scheduler.add_task(low_priority)
    scheduler.add_task(high_priority)

    assert scheduler.due_tasks() == [high_priority, low_priority]


def test_scheduler_tick_returns_empty_list_when_stopped() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    scheduler = Scheduler(clock=FakeClock(now))

    task = Task(command="health.check", trigger=OneShotTrigger(now))
    scheduler.add_task(task)

    assert scheduler.tick() == []


def test_scheduler_tick_executes_due_tasks_when_running() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    scheduler = Scheduler(clock=FakeClock(now))

    task = Task(command="health.check", trigger=OneShotTrigger(now))
    scheduler.add_task(task)

    scheduler.start()

    results = scheduler.tick()

    assert len(results) == 1
    assert results[0].task_id == task.id
    assert results[0].command == "health.check"
    assert results[0].success is True
    assert task.execution_count == 1


def test_scheduler_tick_executes_due_tasks_by_priority() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    scheduler = Scheduler(clock=FakeClock(now))

    low_priority = Task(
        command="backup.run",
        trigger=OneShotTrigger(now),
        priority=100,
    )
    high_priority = Task(
        command="health.check",
        trigger=OneShotTrigger(now),
        priority=10,
    )

    scheduler.add_task(low_priority)
    scheduler.add_task(high_priority)

    scheduler.start()

    results = scheduler.tick()

    assert [result.command for result in results] == [
        "health.check",
        "backup.run",
    ]


def test_scheduler_tick_uses_configured_executor() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    scheduler = Scheduler(
        clock=FakeClock(now),
        executor=FailingTaskExecutor("boom"),
    )

    task = Task(command="health.check", trigger=OneShotTrigger(now))
    scheduler.add_task(task)

    scheduler.start()

    results = scheduler.tick()

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error == "boom"
    assert task.last_error == "boom"


def test_scheduler_start_updates_runtime() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    scheduler = Scheduler(clock=FakeClock(now))

    scheduler.start()

    assert scheduler.running is True
    assert scheduler.runtime.running is True
    assert scheduler.runtime.started_at == now


def test_scheduler_stop_updates_runtime() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    scheduler = Scheduler(clock=FakeClock(now))

    scheduler.start()
    scheduler.stop()

    assert scheduler.running is False
    assert scheduler.runtime.running is False
    assert scheduler.runtime.stopped_at == now


def test_scheduler_tick_records_statistics() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    scheduler = Scheduler(clock=FakeClock(now))

    task = Task(command="health.check", trigger=OneShotTrigger(now))
    scheduler.add_task(task)

    scheduler.start()
    scheduler.tick()

    assert scheduler.runtime.last_tick_at == now
    assert scheduler.runtime.statistics.tick_count == 1
    assert scheduler.runtime.statistics.tasks_executed == 1
    assert scheduler.runtime.statistics.tasks_failed == 0


def test_scheduler_tick_records_failed_statistics() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    scheduler = Scheduler(
        clock=FakeClock(now),
        executor=FailingTaskExecutor("boom"),
    )

    task = Task(command="health.check", trigger=OneShotTrigger(now))
    scheduler.add_task(task)

    scheduler.start()
    scheduler.tick()

    assert scheduler.runtime.statistics.tick_count == 1
    assert scheduler.runtime.statistics.tasks_executed == 0
    assert scheduler.runtime.statistics.tasks_failed == 1
