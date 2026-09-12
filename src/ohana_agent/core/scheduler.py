"""Task scheduler for Shikamaru."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ohana_agent.core.event import Event
from ohana_agent.core.events import EventBus


@dataclass(slots=True)
class ScheduledJob:
    """A scheduled job."""

    name: str
    interval: timedelta
    callback: Callable[[], None]
    id: str = field(default_factory=lambda: str(uuid4()))
    next_run: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class SchedulerJobExecuted(Event):
    """Event published when a scheduled job has been executed."""

    job_id: str = ""
    job_name: str = ""


class Scheduler:
    """Simple synchronous scheduler."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._jobs: list[ScheduledJob] = []

    def every(
        self,
        *,
        name: str,
        seconds: int,
        callback: Callable[[], None],
    ) -> ScheduledJob:
        """Register a job executed every given number of seconds."""
        job = ScheduledJob(
            name=name,
            interval=timedelta(seconds=seconds),
            callback=callback,
        )
        self._jobs.append(job)
        return job

    def tick(self) -> None:
        """Execute all due jobs once."""
        now = datetime.now(UTC)

        for job in self._jobs:
            if job.next_run <= now:
                job.callback()
                job.next_run = now + job.interval
                self._event_bus.publish(
                    SchedulerJobExecuted(
                        job_id=job.id,
                        job_name=job.name,
                    )
                )

    def jobs(self) -> list[ScheduledJob]:
        """Return registered jobs."""
        return list(self._jobs)
