"""Daytime incident work waits for the 05:00 batch instead of expiring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ohana_agent.api.service import AdministrationService
from ohana_agent.infrastructure.repository import InfrastructureConfigurationRepository
from ohana_agent.jobs.repository import DistributedJobRepository

PARIS = ZoneInfo("Europe/Paris")
WORKER = "katsuyu-bubule"
MAC = "AA:BB:CC:DD:EE:FF"
AI = {
    "incident_id": "55555555-5555-4555-8555-555555555555",
    "question": "Pourquoi ?",
    "evidence": [{"source": "x", "content": "y"}],
}


class Clock:
    def __init__(self, paris: datetime) -> None:
        self.now = paris.astimezone(UTC)

    def __call__(self) -> datetime:
        return self.now


def _logs(clock: Clock) -> dict[str, object]:
    return {
        "sources": ["ha-01"],
        "window_started_at": (clock.now - timedelta(hours=1)).isoformat(),
        "window_ended_at": clock.now.isoformat(),
        "max_bytes_per_source": 1048576,
    }


def _payload(clock: Clock, job_id: str, kind: str, parameters: dict, timeout=900):
    return {
        "protocol_version": 1,
        "job_id": job_id,
        "type": kind,
        "created_at": clock.now.isoformat(),
        "parameters": parameters,
        "timeout": timeout,
    }


def _setup(tmp_path: Path, paris: datetime):
    clock = Clock(paris)
    infra = tmp_path / "infrastructure.yaml"
    infra.write_text("{}\n", encoding="utf-8")
    repository = DistributedJobRepository(
        tmp_path / "jobs.db", clock=clock, worker_available_seconds=30
    )
    repository.register_worker(
        {
            "worker_id": WORKER,
            "capabilities": ["ai.inference", "logs.health_check", "backup.infra"],
            "platform": "Windows 11",
            "worker_version": "0.13.2",
            "wake_on_lan_mac_address": MAC,
        }
    )
    clock.now += timedelta(seconds=31)  # Bubule has gone silent: it is off.
    sent: list[str] = []
    service = AdministrationService(
        infrastructure_repository=InfrastructureConfigurationRepository(infra),
        job_repository=repository,
        wake_timeout_seconds=180,
        wake_sender=sent.append,
        wake_enabled=True,
        wake_batch_window_seconds=600,
        wake_planned_window_start_hour=0,
        wake_planned_window_end_hour=5,
    )
    return clock, repository, service, sent


@pytest.fixture
def day(tmp_path: Path):
    clock, repository, service, sent = _setup(
        tmp_path, datetime(2026, 8, 19, 10, 0, tzinfo=PARIS)
    )
    yield clock, repository, service, sent
    repository.close()


def _parameters(kind: str, clock: Clock) -> dict[str, object]:
    if kind == "ai.inference":
        return AI
    if kind == "logs.health_check":
        return _logs(clock)
    return {
        "source": "ha-01",
        "window_started_at": (clock.now - timedelta(hours=1)).isoformat(),
        "window_ended_at": clock.now.isoformat(),
        "pattern": "error",
        "incident_id": AI["incident_id"],
    }


@pytest.mark.parametrize(
    "kind", ["ai.inference", "logs.health_check", "logs.investigate"]
)
def test_daytime_incident_work_is_kept_until_the_next_batch(day, kind) -> None:
    clock, repository, service, _ = day
    job_id = "77777777-7777-4777-8777-777777777777"

    service.create_job(_payload(clock, job_id, kind, _parameters(kind, clock)))

    # 10:00:31 Paris to 05:00 next day is 18 h 59 min 29 s, plus the wake delay.
    assert repository.get(job_id).timeout == 900 + 68369 + 180


def test_a_backup_asked_by_hand_is_not_deferred(day) -> None:
    clock, repository, service, _ = day
    service.create_job(
        _payload(
            clock,
            "88888888-8888-4888-8888-888888888888",
            "backup.infra",
            {
                "backup_id": "20260819T080000Z",
                "recipient": "age1" + "q" * 58,
                "compression_level": 6,
            },
            timeout=3600,
        )
    )

    assert repository.get("88888888-8888-4888-8888-888888888888").timeout == 3600


def test_deferred_job_survives_the_day_and_wakes_bubule_at_five(day) -> None:
    clock, repository, service, sent = day
    job_id = "99999999-9999-4999-8999-999999999999"
    service.create_job(_payload(clock, job_id, "ai.inference", AI))

    clock.now += timedelta(hours=10)  # 20:00 Paris, long past the old 15 minutes
    service.dispatch_due_wake_requests(now=clock.now)
    assert repository.get(job_id).status.value == "WAITING_WORKER"
    assert sent == []

    clock.now = datetime(2026, 8, 20, 5, 0, 30, tzinfo=PARIS).astimezone(UTC)
    service.dispatch_due_wake_requests(now=clock.now)

    assert sent == [MAC]
    assert repository.get(job_id).status.value == "WAITING_WORKER"


def test_deferral_counts_real_hours_across_the_autumn_clock_change(tmp_path) -> None:
    clock, repository, service, _ = _setup(
        tmp_path, datetime(2026, 10, 24, 10, 0, tzinfo=PARIS)
    )
    try:
        job_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        service.create_job(_payload(clock, job_id, "ai.inference", AI))

        # 25/10 has 25 hours: 10:00:31 CEST to 05:00 CET is 19 h 59 min 29 s.
        assert repository.get(job_id).timeout == 900 + 71969 + 180
    finally:
        repository.close()


def test_night_work_still_waits_for_the_same_morning(tmp_path) -> None:
    clock, repository, service, _ = _setup(
        tmp_path, datetime(2026, 8, 20, 3, 0, tzinfo=PARIS)
    )
    try:
        job_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        service.create_job(_payload(clock, job_id, "ai.inference", AI))

        # 03:00:31 to 05:00 is 1 h 59 min 29 s.
        assert repository.get(job_id).timeout == 900 + 7169 + 180
    finally:
        repository.close()
