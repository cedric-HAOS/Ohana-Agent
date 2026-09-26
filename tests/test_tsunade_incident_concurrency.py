"""Vision polls and observations share one SQLite connection safely."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.tsunade.incidents import TsunadeIncidentRepository

STARTED = datetime(2026, 9, 26, 19, 27, tzinfo=UTC)


def _observation(service: str, healthy: bool, at: datetime) -> Observation:
    status = ObservationStatus.HEALTHY if healthy else ObservationStatus.UNHEALTHY
    return Observation(
        node="infra-01",
        service=service,
        capability="ntp.query",
        status=status,
        success=healthy,
        message=f"{service} is {status.value}",
        source="ntp.query",
        id=uuid4(),
        timestamp=at,
        metadata={"device_id": "infra-01"},
    )


@pytest.fixture
def repository(tmp_path: Path):
    repository = TsunadeIncidentRepository(tmp_path / "control.db")
    yield repository
    repository.close()


def test_incidents_are_built_while_holding_the_connection_lock(repository) -> None:
    incident = repository.process(_observation("chrony", False, STARTED))
    build = repository._incident  # noqa: SLF001
    unlocked: list[str] = []

    def guarded(row, *, include_events):
        if not repository._lock._is_owned():  # noqa: SLF001
            unlocked.append(row["incident_id"])
        return build(row, include_events=include_events)

    repository._incident = guarded  # noqa: SLF001
    repository.list(state="all")
    repository.get(incident.incident_id)

    assert unlocked == []


def test_concurrent_polls_during_observations_never_fail(repository) -> None:
    for index in range(20):
        repository.process(_observation(f"service-{index}", False, STARTED))

    def observe(step: int) -> None:
        at = STARTED + timedelta(seconds=step + 1)
        repository.process(_observation(f"service-{step % 20}", step % 2 == 0, at))

    def poll(_step: int) -> int:
        return len(repository.list(state="all"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(observe, step) for step in range(200)]
        futures += [pool.submit(poll, step) for step in range(200)]
        for future in futures:
            future.result()
