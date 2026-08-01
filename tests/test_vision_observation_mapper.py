from datetime import UTC, datetime
from uuid import UUID

import pytest

from observer import Observation, ObservationStatus
from observer.exporters import VisionObservationMapper


def build_observation(
    *,
    status: ObservationStatus = ObservationStatus.HEALTHY,
    latency_ms: float | None = 12.5,
) -> Observation:
    """Build a stable observation used by mapper tests."""
    return Observation(
        id=UUID("31ccf5d8-5af0-49c7-ae67-b74391c50173"),
        timestamp=datetime(
            2026,
            7,
            15,
            12,
            30,
            tzinfo=UTC,
        ),
        node="infra-01",
        service="dns-primary",
        capability="dns.resolve",
        status=status,
        success=status is ObservationStatus.HEALTHY,
        message="DNS resolution succeeded.",
        source="dns.resolve",
        latency_ms=latency_ms,
        metadata={
            "hostname": "example.com",
            "server": "192.168.1.10",
        },
    )


def test_mapper_builds_vision_observation_payload() -> None:
    mapper = VisionObservationMapper()

    payload = mapper.to_payload(build_observation())

    assert payload == {
        "capability_id": "dns.resolve",
        "service_id": "dns-primary",
        "node_id": "infra-01",
        "status": "healthy",
        "observed_at": "2026-07-15T12:30:00+00:00",
        "latency_ms": 12.5,
        "metadata": {
            "hostname": "example.com",
            "server": "192.168.1.10",
            "agent_observation": {
                "id": "31ccf5d8-5af0-49c7-ae67-b74391c50173",
                "source": "dns.resolve",
                "success": True,
                "message": "DNS resolution succeeded.",
            },
        },
    }


@pytest.mark.parametrize(
    ("agent_status", "vision_status"),
    [
        (ObservationStatus.HEALTHY, "healthy"),
        (ObservationStatus.SUSPENDED, "unknown"),
        (ObservationStatus.DEGRADED, "degraded"),
        (ObservationStatus.UNHEALTHY, "unavailable"),
        (ObservationStatus.UNKNOWN, "unknown"),
    ],
)
def test_mapper_converts_status_to_vision_contract(
    agent_status: ObservationStatus,
    vision_status: str,
) -> None:
    mapper = VisionObservationMapper()

    payload = mapper.to_payload(
        build_observation(status=agent_status),
    )

    assert payload["status"] == vision_status


def test_mapper_preserves_null_latency() -> None:
    mapper = VisionObservationMapper()

    payload = mapper.to_payload(
        build_observation(latency_ms=None),
    )

    assert payload["latency_ms"] is None


def test_mapper_does_not_modify_observation_metadata() -> None:
    mapper = VisionObservationMapper()
    observation = build_observation()
    original_metadata = observation.metadata.copy()

    mapper.to_payload(observation)

    assert observation.metadata == original_metadata


def test_mapper_only_emits_fields_accepted_by_vision() -> None:
    mapper = VisionObservationMapper()

    payload = mapper.to_payload(build_observation())

    assert set(payload) == {
        "capability_id",
        "service_id",
        "node_id",
        "status",
        "observed_at",
        "latency_ms",
        "metadata",
    }
