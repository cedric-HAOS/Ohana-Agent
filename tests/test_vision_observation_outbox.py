"""Tests for the durable Ohana-Vision observation outbox."""

from pathlib import Path
from uuid import uuid4

from observer.exporters import VisionObservationOutbox


def payload() -> dict[str, object]:
    return {
        "observation_id": str(uuid4()),
        "capability_id": "dns.resolve",
        "service_id": "dns-primary",
        "node_id": "infra-01",
        "status": "healthy",
        "observed_at": "2026-08-10T10:00:00+00:00",
        "metadata": {},
    }


def test_outbox_restores_pending_observation_after_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "outbox.db"
    observation = payload()
    first = VisionObservationOutbox(database_path)
    first.enqueue(observation)
    first.close()

    restored = VisionObservationOutbox(database_path)

    assert restored.pending_count == 1
    assert restored.oldest() is not None
    assert restored.oldest().payload == observation
    restored.close()


def test_outbox_deduplicates_observation_identity(tmp_path: Path) -> None:
    outbox = VisionObservationOutbox(tmp_path / "outbox.db")
    observation = payload()

    outbox.enqueue(observation)
    outbox.enqueue(observation)

    assert outbox.pending_count == 1
    outbox.close()


def test_outbox_retains_failures_until_delivery(tmp_path: Path) -> None:
    outbox = VisionObservationOutbox(tmp_path / "outbox.db")
    observation = payload()
    observation_id = str(observation["observation_id"])
    outbox.enqueue(observation)

    outbox.mark_failed(observation_id, "Vision unavailable")

    entry = outbox.oldest()
    assert entry is not None
    assert entry.attempts == 1
    outbox.mark_delivered(observation_id)
    assert outbox.pending_count == 0
    outbox.close()


def test_outbox_discards_oldest_payloads_at_the_configured_limit(
    tmp_path: Path,
) -> None:
    outbox = VisionObservationOutbox(tmp_path / "outbox.db", max_entries=2)
    observations = [payload() for _index in range(3)]

    for observation in observations:
        outbox.enqueue(observation)

    assert outbox.pending_count == 2
    assert outbox.oldest() is not None
    assert outbox.oldest().payload == observations[1]
    outbox.close()
