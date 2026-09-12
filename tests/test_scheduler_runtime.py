from datetime import UTC, datetime

from ohana_agent.scheduler import SchedulerRuntime, SchedulerState


def test_scheduler_runtime_defaults_to_stopped() -> None:
    runtime = SchedulerRuntime()

    assert runtime.state == SchedulerState.STOPPED
    assert runtime.running is False
    assert runtime.started_at is None
    assert runtime.stopped_at is None
    assert runtime.last_tick_at is None


def test_scheduler_runtime_can_mark_starting() -> None:
    runtime = SchedulerRuntime()

    runtime.mark_starting()

    assert runtime.state == SchedulerState.STARTING


def test_scheduler_runtime_can_mark_running() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    runtime = SchedulerRuntime()

    runtime.mark_running(now)

    assert runtime.state == SchedulerState.RUNNING
    assert runtime.running is True
    assert runtime.started_at == now
    assert runtime.stopped_at is None


def test_scheduler_runtime_can_mark_stopping() -> None:
    runtime = SchedulerRuntime()

    runtime.mark_stopping()

    assert runtime.state == SchedulerState.STOPPING


def test_scheduler_runtime_can_mark_stopped() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    runtime = SchedulerRuntime()

    runtime.mark_stopped(now)

    assert runtime.state == SchedulerState.STOPPED
    assert runtime.running is False
    assert runtime.stopped_at == now


def test_scheduler_runtime_records_tick() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    runtime = SchedulerRuntime()

    runtime.record_tick(now)

    assert runtime.last_tick_at == now
    assert runtime.statistics.tick_count == 1
