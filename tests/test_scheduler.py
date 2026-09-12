"""Tests for the Shikamaru scheduler."""

from datetime import UTC, datetime, timedelta

from ohana_agent.core.events import EventBus
from ohana_agent.core.scheduler import Scheduler, SchedulerJobExecuted


def test_register_job() -> None:
    """A job can be registered."""
    bus = EventBus()
    scheduler = Scheduler(bus)

    def callback() -> None:
        pass

    job = scheduler.every(name="test-job", seconds=5, callback=callback)

    assert job.name == "test-job"
    assert job.interval == timedelta(seconds=5)
    assert scheduler.jobs() == [job]


def test_tick_executes_due_job() -> None:
    """tick() executes a due job."""
    bus = EventBus()
    scheduler = Scheduler(bus)
    calls: list[str] = []

    def callback() -> None:
        calls.append("called")

    job = scheduler.every(name="test-job", seconds=5, callback=callback)
    job.next_run = datetime.now(UTC) - timedelta(seconds=1)

    scheduler.tick()

    assert calls == ["called"]


def test_tick_does_not_execute_job_before_due_time() -> None:
    """tick() does not execute a job before its due time."""
    bus = EventBus()
    scheduler = Scheduler(bus)
    calls: list[str] = []

    def callback() -> None:
        calls.append("called")

    job = scheduler.every(name="test-job", seconds=5, callback=callback)
    job.next_run = datetime.now(UTC) + timedelta(seconds=60)

    scheduler.tick()

    assert calls == []


def test_tick_updates_next_run_after_execution() -> None:
    """tick() updates next_run after executing a job."""
    bus = EventBus()
    scheduler = Scheduler(bus)

    def callback() -> None:
        pass

    job = scheduler.every(name="test-job", seconds=5, callback=callback)
    job.next_run = datetime.now(UTC) - timedelta(seconds=1)

    scheduler.tick()

    assert job.next_run > datetime.now(UTC)


def test_tick_publishes_job_executed_event() -> None:
    """tick() publishes an event after executing a job."""
    bus = EventBus()
    scheduler = Scheduler(bus)
    received: list[SchedulerJobExecuted] = []

    def on_job_executed(event: SchedulerJobExecuted) -> None:
        received.append(event)

    def callback() -> None:
        pass

    bus.subscribe(SchedulerJobExecuted, on_job_executed)

    job = scheduler.every(name="test-job", seconds=5, callback=callback)
    job.next_run = datetime.now(UTC) - timedelta(seconds=1)

    scheduler.tick()

    assert len(received) == 1
    assert received[0].job_id == job.id
    assert received[0].job_name == "test-job"


def test_multiple_due_jobs_are_executed() -> None:
    """tick() executes all due jobs."""
    bus = EventBus()
    scheduler = Scheduler(bus)
    calls: list[str] = []

    def callback_a() -> None:
        calls.append("a")

    def callback_b() -> None:
        calls.append("b")

    job_a = scheduler.every(name="job-a", seconds=5, callback=callback_a)
    job_b = scheduler.every(name="job-b", seconds=5, callback=callback_b)

    job_a.next_run = datetime.now(UTC) - timedelta(seconds=1)
    job_b.next_run = datetime.now(UTC) - timedelta(seconds=1)

    scheduler.tick()

    assert calls == ["a", "b"]


def test_jobs_returns_copy() -> None:
    """jobs() returns a copy of the registered jobs list."""
    bus = EventBus()
    scheduler = Scheduler(bus)

    def callback() -> None:
        pass

    scheduler.every(name="test-job", seconds=5, callback=callback)

    jobs = scheduler.jobs()
    jobs.clear()

    assert len(scheduler.jobs()) == 1
