from builder import InfrastructureBuilder
from infrastructure.enums import EndpointType, ServiceType
from loader import InfrastructureLoader


def build_infrastructure():
    loader = InfrastructureLoader()
    builder = InfrastructureBuilder()

    config = loader.load("config/infrastructure.example.yaml")

    return builder.build(config)


def test_builder_builds_infrastructure() -> None:
    infrastructure = build_infrastructure()

    assert infrastructure.name == "Ohana House"


def test_builder_builds_nodes() -> None:
    infrastructure = build_infrastructure()

    assert len(infrastructure.nodes) == 6
    assert {node.name for node in infrastructure.nodes} == {
        "box-01",
        "infra-01",
        "zwave-01",
        "linky-01",
        "ha-01",
        "shelly-cuisine",
    }


def test_builder_builds_node_endpoints() -> None:
    infrastructure = build_infrastructure()

    node = next(node for node in infrastructure.nodes if node.name == "infra-01")

    assert len(node.endpoints) == 1
    assert node.endpoints[0].type == EndpointType.IP
    assert node.endpoints[0].address == "192.168.1.10"


def test_builder_builds_services() -> None:
    infrastructure = build_infrastructure()

    node = next(node for node in infrastructure.nodes if node.name == "infra-01")

    assert len(node.services) == 2
    assert node.services[0].name == "dhcp-primary"
    assert node.services[0].type == ServiceType.DHCP


def test_builder_builds_service_endpoint() -> None:
    infrastructure = build_infrastructure()

    node = next(node for node in infrastructure.nodes if node.name == "infra-01")
    service = next(
        service for service in node.services if service.name == "dhcp-primary"
    )

    assert service.endpoint is not None
    assert service.endpoint.type == EndpointType.IP
    assert service.endpoint.address == "192.168.1.10"
    assert service.endpoint.port == 67
