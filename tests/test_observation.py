from datetime import UTC
from uuid import UUID

from ohana_agent.observation import Observation, ObservationStatus


def test_observation_can_be_created() -> None:
    observation = Observation(
        node="infra-01",
        service="dns-primary",
        capability="dns",
        status=ObservationStatus.HEALTHY,
        success=True,
        message="DNS resolution succeeded.",
        source="dns-plugin",
        latency_ms=12.4,
        metadata={
            "hostname": "example.com",
        },
    )

    assert observation.node == "infra-01"
    assert observation.service == "dns-primary"
    assert observation.capability == "dns"

    assert observation.status == ObservationStatus.HEALTHY
    assert observation.success is True

    assert observation.message == "DNS resolution succeeded."
    assert observation.source == "dns-plugin"

    assert observation.latency_ms == 12.4

    assert observation.metadata["hostname"] == "example.com"


def test_observation_generates_uuid() -> None:
    observation = Observation(
        node="infra-01",
        service="dns-primary",
        capability="dns",
        status=ObservationStatus.UNKNOWN,
        success=False,
        message="Unknown",
        source="test",
    )

    assert isinstance(observation.id, UUID)


def test_observation_generates_utc_timestamp() -> None:
    observation = Observation(
        node="infra-01",
        service="dns-primary",
        capability="dns",
        status=ObservationStatus.UNKNOWN,
        success=False,
        message="Unknown",
        source="test",
    )

    assert observation.timestamp.tzinfo == UTC


def test_observation_metadata_defaults_to_empty_dict() -> None:
    observation = Observation(
        node="infra-01",
        service="dns-primary",
        capability="dns",
        status=ObservationStatus.UNKNOWN,
        success=False,
        message="Unknown",
        source="test",
    )

    assert observation.metadata == {}
