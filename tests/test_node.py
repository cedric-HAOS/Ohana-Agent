from ohana_agent.infrastructure import (
    Endpoint,
    EndpointType,
    Node,
    Service,
    ServiceType,
)


def test_node_can_be_created() -> None:
    node = Node(name="INFRA-01", description="Infrastructure server")

    assert node.name == "INFRA-01"
    assert node.description == "Infrastructure server"
    assert node.enabled is True
    assert node.endpoints == []
    assert node.services == []


def test_node_can_be_disabled() -> None:
    node = Node(name="INFRA-01", enabled=False)

    assert node.is_enabled() is False


def test_node_can_add_endpoint() -> None:
    node = Node(name="INFRA-01")
    endpoint = Endpoint(type=EndpointType.IP, address="192.168.1.10")

    node.add_endpoint(endpoint)

    assert node.endpoints == [endpoint]


def test_node_can_add_service() -> None:
    node = Node(name="INFRA-01")
    service = Service(name="DNS", type=ServiceType.DNS)

    node.add_service(service)

    assert node.services == [service]


def test_node_can_get_endpoint_by_type() -> None:
    node = Node(name="INFRA-01")
    endpoint = Endpoint(type=EndpointType.IP, address="192.168.1.10")

    node.add_endpoint(endpoint)

    assert node.get_endpoint(EndpointType.IP) is endpoint


def test_node_returns_none_for_unknown_endpoint_type() -> None:
    node = Node(name="INFRA-01")

    assert node.get_endpoint(EndpointType.IP) is None


def test_node_can_get_endpoint_by_address() -> None:
    node = Node(name="INFRA-01")
    endpoint = Endpoint(type=EndpointType.IP, address="192.168.1.10")

    node.add_endpoint(endpoint)

    assert node.get_endpoint_by_address("192.168.1.10") is endpoint


def test_node_returns_none_for_unknown_endpoint_address() -> None:
    node = Node(name="INFRA-01")

    assert node.get_endpoint_by_address("192.168.1.10") is None


def test_node_can_get_service_by_type() -> None:
    node = Node(name="INFRA-01")
    service = Service(name="DNS", type=ServiceType.DNS)

    node.add_service(service)

    assert node.get_service(ServiceType.DNS) is service


def test_node_returns_none_for_unknown_service_type() -> None:
    node = Node(name="INFRA-01")

    assert node.get_service(ServiceType.DNS) is None


def test_node_can_get_service_by_name() -> None:
    node = Node(name="INFRA-01")
    service = Service(name="DNS", type=ServiceType.DNS)

    node.add_service(service)

    assert node.get_service_by_name("DNS") is service


def test_node_returns_none_for_unknown_service_name() -> None:
    node = Node(name="INFRA-01")

    assert node.get_service_by_name("DNS") is None
