import json
from datetime import UTC, datetime
from uuid import UUID

from ohana_agent.observation import (
    Observation,
    ObservationSerializer,
    ObservationStatus,
)


def build_observation() -> Observation:
    return Observation(
        id=UUID("12345678-1234-5678-1234-567812345678"),
        timestamp=datetime(
            2026,
            7,
            10,
            8,
            30,
            15,
            tzinfo=UTC,
        ),
        node="zwave-01",
        service="dns-primary",
        capability="dns",
        status=ObservationStatus.HEALTHY,
        success=True,
        message="DNS resolution succeeded.",
        source="dns-plugin",
        latency_ms=12.4,
        metadata={
            "hostname": "example.com",
            "server": "192.168.1.54",
            "resolved_address": "93.184.216.34",
        },
    )


def test_serializer_converts_observation_to_dict() -> None:
    serializer = ObservationSerializer()
    observation = build_observation()

    data = serializer.to_dict(observation)

    assert data == {
        "id": "12345678-1234-5678-1234-567812345678",
        "timestamp": "2026-07-10T08:30:15+00:00",
        "source": "dns-plugin",
        "node": "zwave-01",
        "service": "dns-primary",
        "capability": "dns",
        "status": "healthy",
        "success": True,
        "latency_ms": 12.4,
        "message": "DNS resolution succeeded.",
        "metadata": {
            "hostname": "example.com",
            "server": "192.168.1.54",
            "resolved_address": "93.184.216.34",
        },
    }


def test_serializer_converts_observation_to_json() -> None:
    serializer = ObservationSerializer()
    observation = build_observation()

    payload = serializer.to_json(observation)
    data = json.loads(payload)

    assert data["node"] == "zwave-01"
    assert data["capability"] == "dns"
    assert data["status"] == "healthy"
    assert data["success"] is True


def test_serializer_preserves_null_latency() -> None:
    serializer = ObservationSerializer()

    observation = Observation(
        node="infra-01",
        service="internet-primary",
        capability="internet",
        status=ObservationStatus.UNKNOWN,
        success=False,
        message="No measurement available.",
        source="internet-plugin",
        latency_ms=None,
    )

    data = serializer.to_dict(observation)

    assert data["latency_ms"] is None


def test_serializer_preserves_unicode() -> None:
    serializer = ObservationSerializer()

    observation = Observation(
        node="infra-01",
        service="dns-primary",
        capability="dns",
        status=ObservationStatus.UNHEALTHY,
        success=False,
        message="Échec de la résolution DNS.",
        source="dns-plugin",
    )

    payload = serializer.to_json(observation)

    assert "Échec de la résolution DNS." in payload
    assert "\\u00c9" not in payload


def test_serializer_supports_indented_json() -> None:
    serializer = ObservationSerializer()
    observation = build_observation()

    payload = serializer.to_json(
        observation,
        indent=2,
    )

    assert "\n" in payload
    assert '  "capability": "dns"' in payload


def test_serializer_does_not_share_metadata_dictionary() -> None:
    serializer = ObservationSerializer()
    observation = build_observation()

    data = serializer.to_dict(observation)
    data["metadata"]["hostname"] = "modified.example.com"

    assert observation.metadata["hostname"] == "example.com"
