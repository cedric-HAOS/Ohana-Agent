from ohana_agent.infrastructure import (
    Endpoint,
    EndpointType,
    HealthStatus,
    Service,
    ServiceType,
)


def test_service_can_be_created() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)

    assert service.name == "DNS"
    assert service.type is ServiceType.DNS
    assert service.endpoint is None
    assert service.health is HealthStatus.UNKNOWN
    assert service.enabled is True


def test_service_can_reference_endpoint() -> None:
    endpoint = Endpoint(type=EndpointType.IP, address="192.168.1.10", port=53)
    service = Service(name="DNS", type=ServiceType.DNS, endpoint=endpoint)

    assert service.endpoint is endpoint


def test_service_can_be_disabled() -> None:
    service = Service(name="MQTT", type=ServiceType.MQTT, enabled=False)

    assert service.is_enabled() is False
