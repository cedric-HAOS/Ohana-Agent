from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.observation.exporters import InMemoryObservationExporter


def build_observation(
    *,
    node: str = "infra-01",
    status: ObservationStatus = ObservationStatus.HEALTHY,
) -> Observation:
    return Observation(
        node=node,
        service="dns-primary",
        capability="dns",
        status=status,
        success=status is ObservationStatus.HEALTHY,
        message="DNS observation completed.",
        source="dns-plugin",
        latency_ms=12.5,
        metadata={
            "hostname": "example.com",
        },
    )


def test_in_memory_exporter_can_be_created() -> None:
    exporter = InMemoryObservationExporter()

    assert exporter.observations == []
    assert exporter.latest() is None


def test_in_memory_exporter_stores_observation() -> None:
    exporter = InMemoryObservationExporter()
    observation = build_observation()

    exporter.export(observation)

    assert exporter.observations == [observation]


def test_in_memory_exporter_returns_latest_observation() -> None:
    exporter = InMemoryObservationExporter()

    first = build_observation(
        node="infra-01",
        status=ObservationStatus.HEALTHY,
    )
    second = build_observation(
        node="zwave-01",
        status=ObservationStatus.DEGRADED,
    )

    exporter.export(first)
    exporter.export(second)

    assert exporter.latest() is second


def test_in_memory_exporter_preserves_observation_order() -> None:
    exporter = InMemoryObservationExporter()

    first = build_observation(node="infra-01")
    second = build_observation(node="zwave-01")

    exporter.export(first)
    exporter.export(second)

    assert exporter.observations == [
        first,
        second,
    ]
