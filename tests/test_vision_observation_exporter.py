from dataclasses import dataclass, field
from typing import Any

from ohana_agent.observation import Observation, ObservationStatus
from ohana_agent.observation.exporters import (
    VisionObservationExporter,
    VisionObservationMapper,
)


@dataclass
class FakeVisionClient:
    """Fake Ohana-Vision client used by tests."""

    payloads: list[dict[str, Any]] = field(default_factory=list)

    def send_observation(
        self,
        payload: dict[str, Any],
    ) -> None:
        self.payloads.append(payload)


def build_observation() -> Observation:
    return Observation(
        node="infra-01",
        service="dns-primary",
        capability="dns.resolve",
        status=ObservationStatus.HEALTHY,
        success=True,
        message="DNS resolution succeeded.",
        source="dns.resolve",
        latency_ms=12.5,
        metadata={
            "hostname": "example.com",
            "server": "192.168.1.10",
        },
    )


def test_vision_exporter_can_be_created() -> None:
    client = FakeVisionClient()
    mapper = VisionObservationMapper()

    exporter = VisionObservationExporter(
        client=client,
        mapper=mapper,
    )

    assert exporter.client is client
    assert exporter.mapper is mapper


def test_vision_exporter_sends_mapped_observation() -> None:
    client = FakeVisionClient()
    exporter = VisionObservationExporter(
        client=client,
        mapper=VisionObservationMapper(),
    )

    exporter.export(build_observation())

    assert len(client.payloads) == 1

    payload = client.payloads[0]

    assert payload["node_id"] == "infra-01"
    assert payload["service_id"] == "dns-primary"
    assert payload["capability_id"] == "dns.resolve"
    assert payload["status"] == "healthy"
    assert payload["latency_ms"] == 12.5


def test_vision_exporter_preserves_business_metadata() -> None:
    client = FakeVisionClient()
    exporter = VisionObservationExporter(
        client=client,
        mapper=VisionObservationMapper(),
    )

    exporter.export(build_observation())

    metadata = client.payloads[0]["metadata"]

    assert metadata["hostname"] == "example.com"
    assert metadata["server"] == "192.168.1.10"


def test_vision_exporter_adds_agent_traceability() -> None:
    client = FakeVisionClient()
    exporter = VisionObservationExporter(
        client=client,
        mapper=VisionObservationMapper(),
    )

    observation = build_observation()

    exporter.export(observation)

    agent_metadata = client.payloads[0]["metadata"]["agent_observation"]

    assert agent_metadata == {
        "id": str(observation.id),
        "source": "dns.resolve",
        "success": True,
        "message": "DNS resolution succeeded.",
    }


def test_vision_exporter_sends_each_observation() -> None:
    client = FakeVisionClient()
    exporter = VisionObservationExporter(
        client=client,
        mapper=VisionObservationMapper(),
    )

    exporter.export(build_observation())
    exporter.export(build_observation())

    assert len(client.payloads) == 2
