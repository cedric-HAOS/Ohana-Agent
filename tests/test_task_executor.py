from datetime import UTC, datetime, timedelta

from ohana_agent.scheduler import (
    DryRunTaskExecutor,
    FailingTaskExecutor,
    IntervalTrigger,
    Task,
    TaskState,
)


def test_dry_run_task_executor_marks_task_finished() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    task = Task(
        command="health.check",
        trigger=IntervalTrigger(timedelta(seconds=30)),
    )
    executor = DryRunTaskExecutor()

    result = executor.execute(task, now)

    assert result.task_id == task.id
    assert result.command == "health.check"
    assert result.success is True
    assert result.started_at == now
    assert result.finished_at == now
    assert result.error is None
    assert task.state == TaskState.WAITING
    assert task.last_started_at == now
    assert task.last_finished_at == now
    assert task.execution_count == 1


def test_failing_task_executor_marks_task_failed() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    task = Task(
        command="health.check",
        trigger=IntervalTrigger(timedelta(seconds=30)),
    )
    executor = FailingTaskExecutor(RuntimeError("boom"))

    result = executor.execute(task, now)

    assert result.task_id == task.id
    assert result.command == "health.check"
    assert result.success is False
    assert result.started_at == now
    assert result.finished_at == now
    assert result.error == "boom"
    assert task.state == TaskState.WAITING
    assert task.last_started_at == now
    assert task.last_failed_at == now
    assert task.last_error == "boom"
    assert task.execution_count == 1


def test_failing_task_executor_accepts_string_error() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    task = Task(
        command="health.check",
        trigger=IntervalTrigger(timedelta(seconds=30)),
    )
    executor = FailingTaskExecutor("failure")

    result = executor.execute(task, now)

    assert result.success is False
    assert result.error == "failure"
    assert task.last_error == "failure"
