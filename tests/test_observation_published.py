from datetime import UTC

from ohana_agent.observation import Observation, ObservationPublished, ObservationStatus


def build_observation() -> Observation:
    return Observation(
        node="infra-01",
        service="dns-primary",
        capability="dns",
        status=ObservationStatus.HEALTHY,
        success=True,
        message="DNS resolution succeeded.",
        source="dns-plugin",
        latency_ms=12.5,
    )


def test_observation_published_contains_observation() -> None:
    observation = build_observation()

    event = ObservationPublished(
        observation=observation,
    )

    assert event.observation is observation


def test_observation_published_has_utc_timestamp() -> None:
    event = ObservationPublished(
        observation=build_observation(),
    )

    assert event.occurred_at.tzinfo == UTC
