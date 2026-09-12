from datetime import UTC, datetime, timedelta

import pytest

from ohana_agent.scheduler import IntervalTrigger, OneShotTrigger, Task, TaskRegistry


def test_task_registry_can_add_and_get_task() -> None:
    registry = TaskRegistry()
    task = Task(
        command="health.check",
        trigger=IntervalTrigger(timedelta(seconds=30)),
    )

    registry.add(task)

    assert registry.get(task.id) == task


def test_task_registry_rejects_duplicate_task_id() -> None:
    registry = TaskRegistry()
    task = Task(
        command="health.check",
        trigger=IntervalTrigger(timedelta(seconds=30)),
    )

    registry.add(task)

    with pytest.raises(ValueError, match=f"task already exists: {task.id}"):
        registry.add(task)


def test_task_registry_removes_task() -> None:
    registry = TaskRegistry()
    task = Task(
        command="health.check",
        trigger=IntervalTrigger(timedelta(seconds=30)),
    )

    registry.add(task)

    removed = registry.remove(task.id)

    assert removed == task
    assert registry.list() == []


def test_task_registry_get_unknown_task_raises_key_error() -> None:
    registry = TaskRegistry()

    with pytest.raises(KeyError, match="task not found: missing"):
        registry.get("missing")


def test_task_registry_remove_unknown_task_raises_key_error() -> None:
    registry = TaskRegistry()

    with pytest.raises(KeyError, match="task not found: missing"):
        registry.remove("missing")


def test_task_registry_checks_task_existence() -> None:
    registry = TaskRegistry()
    task = Task(
        command="health.check",
        trigger=IntervalTrigger(timedelta(seconds=30)),
    )

    registry.add(task)

    assert registry.exists(task.id) is True
    assert registry.exists("missing") is False


def test_task_registry_lists_tasks_by_priority() -> None:
    registry = TaskRegistry()

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

    registry.add(low_priority)
    registry.add(high_priority)

    assert registry.list() == [high_priority, low_priority]


def test_task_registry_returns_due_tasks() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    registry = TaskRegistry()

    due_task = Task(command="health.check", trigger=OneShotTrigger(now))
    later_task = Task(
        command="backup.run",
        trigger=OneShotTrigger(now + timedelta(minutes=5)),
    )

    registry.add(due_task)
    registry.add(later_task)

    assert registry.due_tasks(now) == [due_task]


def test_task_registry_ignores_disabled_due_tasks() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    registry = TaskRegistry()

    task = Task(
        command="health.check",
        trigger=OneShotTrigger(now),
        enabled=False,
    )

    registry.add(task)

    assert registry.due_tasks(now) == []


def test_task_registry_due_tasks_are_sorted_by_priority() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    registry = TaskRegistry()

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

    registry.add(low_priority)
    registry.add(high_priority)

    assert registry.due_tasks(now) == [high_priority, low_priority]


def test_task_registry_can_clear_tasks() -> None:
    registry = TaskRegistry()
    task = Task(
        command="health.check",
        trigger=IntervalTrigger(timedelta(seconds=30)),
    )

    registry.add(task)
    registry.clear()

    assert registry.list() == []
