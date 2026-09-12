from ohana_agent.infrastructure import (
    Endpoint,
    EndpointType,
    Infrastructure,
    Node,
    Service,
    ServiceType,
)


def test_infrastructure_can_be_created() -> None:
    infrastructure = Infrastructure(name="Ohana")

    assert infrastructure.name == "Ohana"
    assert infrastructure.nodes == []
    assert infrastructure.metadata == {}


def test_infrastructure_can_add_node() -> None:
    infrastructure = Infrastructure(name="Ohana")
    node = Node(name="INFRA-01")

    infrastructure.add_node(node)

    assert infrastructure.nodes == [node]


def test_infrastructure_can_get_node_by_name() -> None:
    infrastructure = Infrastructure(name="Ohana")
    node = Node(name="INFRA-01")

    infrastructure.add_node(node)

    assert infrastructure.get_node("INFRA-01") is node


def test_infrastructure_returns_none_for_unknown_node() -> None:
    infrastructure = Infrastructure(name="Ohana")

    assert infrastructure.get_node("UNKNOWN") is None


def test_infrastructure_can_find_service_by_type() -> None:
    infrastructure = Infrastructure(name="Ohana")
    node = Node(name="INFRA-01")
    service = Service(name="DNS", type=ServiceType.DNS)

    node.add_service(service)
    infrastructure.add_node(node)

    assert infrastructure.find_service(ServiceType.DNS) is service


def test_infrastructure_returns_none_for_unknown_service_type() -> None:
    infrastructure = Infrastructure(name="Ohana")

    assert infrastructure.find_service(ServiceType.DNS) is None


def test_infrastructure_can_find_all_services_by_type() -> None:
    infrastructure = Infrastructure(name="Ohana")
    first_node = Node(name="DNS-01")
    second_node = Node(name="DNS-02")
    first_service = Service(name="DNS primary", type=ServiceType.DNS)
    second_service = Service(name="DNS secondary", type=ServiceType.DNS)

    first_node.add_service(first_service)
    second_node.add_service(second_service)
    infrastructure.add_node(first_node)
    infrastructure.add_node(second_node)

    assert infrastructure.find_services(ServiceType.DNS) == [
        first_service,
        second_service,
    ]


def test_infrastructure_returns_empty_list_for_unknown_services() -> None:
    infrastructure = Infrastructure(name="Ohana")

    assert infrastructure.find_services(ServiceType.DNS) == []


def test_infrastructure_can_find_endpoint_by_address() -> None:
    infrastructure = Infrastructure(name="Ohana")
    node = Node(name="INFRA-01")
    endpoint = Endpoint(type=EndpointType.IP, address="192.168.1.10")

    node.add_endpoint(endpoint)
    infrastructure.add_node(node)

    assert infrastructure.find_endpoint("192.168.1.10") is endpoint


def test_infrastructure_returns_none_for_unknown_endpoint_address() -> None:
    infrastructure = Infrastructure(name="Ohana")

    assert infrastructure.find_endpoint("192.168.1.10") is None


def test_infrastructure_can_find_endpoint_by_type() -> None:
    infrastructure = Infrastructure(name="Ohana")
    node = Node(name="INFRA-01")
    endpoint = Endpoint(type=EndpointType.MQTT, address="mqtt://192.168.1.10")

    node.add_endpoint(endpoint)
    infrastructure.add_node(node)

    assert infrastructure.find_endpoint_by_type(EndpointType.MQTT) is endpoint


def test_infrastructure_returns_none_for_unknown_endpoint_type() -> None:
    infrastructure = Infrastructure(name="Ohana")

    assert infrastructure.find_endpoint_by_type(EndpointType.MQTT) is None
