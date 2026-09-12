from dataclasses import dataclass, field

from ohana_agent.observation import (
    Observation,
    ObservationEventPublisher,
    ObservationPublished,
    ObservationStatus,
)


@dataclass
class FakeEventPublisher:
    """Fake event publisher used by tests."""

    events: list[object] = field(default_factory=list)

    def publish(self, event: object) -> None:
        self.events.append(event)


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


def test_observation_event_publisher_can_be_created() -> None:
    event_publisher = FakeEventPublisher()

    publisher = ObservationEventPublisher(
        event_publisher=event_publisher,
    )

    assert publisher.event_publisher is event_publisher


def test_observation_event_publisher_publishes_event() -> None:
    event_publisher = FakeEventPublisher()
    publisher = ObservationEventPublisher(
        event_publisher=event_publisher,
    )
    observation = build_observation()

    event = publisher.publish(observation)

    assert event_publisher.events == [event]


def test_observation_event_publisher_returns_published_event() -> None:
    event_publisher = FakeEventPublisher()
    publisher = ObservationEventPublisher(
        event_publisher=event_publisher,
    )
    observation = build_observation()

    event = publisher.publish(observation)

    assert isinstance(event, ObservationPublished)
    assert event.observation is observation


def test_each_publication_creates_a_distinct_event() -> None:
    event_publisher = FakeEventPublisher()
    publisher = ObservationEventPublisher(
        event_publisher=event_publisher,
    )
    observation = build_observation()

    first_event = publisher.publish(observation)
    second_event = publisher.publish(observation)

    assert first_event is not second_event
    assert event_publisher.events == [
        first_event,
        second_event,
    ]
