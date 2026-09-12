from datetime import UTC, datetime, timedelta

import pytest

from ohana_agent.scheduler import IntervalTrigger, OneShotTrigger, Task, TaskState


def test_task_uses_command_as_default_name() -> None:
    trigger = IntervalTrigger(timedelta(seconds=30))
    task = Task(command="health.check", trigger=trigger)

    assert task.name == "health.check"


def test_task_rejects_empty_command() -> None:
    trigger = IntervalTrigger(timedelta(seconds=30))

    with pytest.raises(ValueError, match="task command must not be empty"):
        Task(command=" ", trigger=trigger)


def test_task_has_unique_id() -> None:
    trigger = IntervalTrigger(timedelta(seconds=30))

    first = Task(command="health.check", trigger=trigger)
    second = Task(command="health.check", trigger=trigger)

    assert first.id != second.id


def test_task_is_not_due_when_disabled() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = OneShotTrigger(now)
    task = Task(command="health.check", trigger=trigger, enabled=False)

    assert task.is_due(now) is False


def test_task_is_due_when_enabled_and_trigger_is_due() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = OneShotTrigger(now)
    task = Task(command="health.check", trigger=trigger)

    assert task.is_due(now) is True


def test_disabled_task_has_no_next_run() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = OneShotTrigger(now)
    task = Task(command="health.check", trigger=trigger, enabled=False)

    assert task.next_run_at(now) is None


def test_task_mark_started() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = IntervalTrigger(timedelta(seconds=30))
    task = Task(command="health.check", trigger=trigger)

    task.mark_started(now)

    assert task.state == TaskState.RUNNING
    assert task.last_started_at == now
    assert task.last_error is None


def test_task_mark_finished() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = IntervalTrigger(timedelta(seconds=30))
    task = Task(command="health.check", trigger=trigger)

    task.mark_started(now)
    task.mark_finished(now + timedelta(seconds=1))

    assert task.state == TaskState.WAITING
    assert task.last_finished_at == now + timedelta(seconds=1)
    assert trigger.fire_count == 1


def test_task_mark_failed() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = IntervalTrigger(timedelta(seconds=30))
    task = Task(command="health.check", trigger=trigger)

    task.mark_started(now)
    task.mark_failed(now + timedelta(seconds=1), RuntimeError("boom"))

    assert task.state == TaskState.WAITING
    assert task.last_failed_at == now + timedelta(seconds=1)
    assert task.last_error == "boom"
    assert trigger.fire_count == 1


def test_task_can_be_disabled_and_enabled() -> None:
    trigger = IntervalTrigger(timedelta(seconds=30))
    task = Task(command="health.check", trigger=trigger)

    task.disable()

    assert task.enabled is False
    assert task.state == TaskState.DISABLED

    task.enable()

    assert task.enabled is True
    assert task.state == TaskState.IDLE


def test_task_has_default_priority() -> None:
    trigger = IntervalTrigger(timedelta(seconds=30))
    task = Task(command="health.check", trigger=trigger)

    assert task.priority == 100


def test_task_rejects_negative_priority() -> None:
    trigger = IntervalTrigger(timedelta(seconds=30))

    with pytest.raises(
        ValueError,
        match="task priority must be greater than or equal to zero",
    ):
        Task(command="health.check", trigger=trigger, priority=-1)


def test_task_exposes_execution_observation() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    trigger = IntervalTrigger(timedelta(seconds=30))
    task = Task(command="health.check", trigger=trigger)

    task.mark_started(now)
    task.mark_finished(now + timedelta(seconds=1))

    assert task.execution_count == 1
    assert task.last_execution == now + timedelta(seconds=1)
