from ohana_agent.infrastructure import (
    Endpoint,
    EndpointType,
    HealthStatus,
    Node,
    NodeRuntime,
    Service,
    ServiceType,
)


def test_node_runtime_can_be_created() -> None:
    node = Node(name="INFRA-01")
    runtime = NodeRuntime(node=node)

    assert runtime.node is node
    assert runtime.health is HealthStatus.UNKNOWN
    assert runtime.endpoint_runtimes == []
    assert runtime.service_runtimes == []
    assert runtime.last_update is None


def test_node_runtime_can_update_health() -> None:
    node = Node(name="INFRA-01")
    runtime = NodeRuntime(node=node)

    runtime.update_health(HealthStatus.HEALTHY)

    assert runtime.health is HealthStatus.HEALTHY
    assert runtime.last_update is not None


def test_node_runtime_can_be_created_from_node() -> None:
    endpoint = Endpoint(type=EndpointType.IP, address="192.168.1.10")
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", endpoints=[endpoint], services=[service])

    runtime = NodeRuntime.from_node(node)

    assert runtime.node is node
    assert len(runtime.endpoint_runtimes) == 1
    assert len(runtime.service_runtimes) == 1
    assert runtime.endpoint_runtimes[0].endpoint is endpoint
    assert runtime.service_runtimes[0].service is service


def test_node_runtime_can_get_endpoint_runtime() -> None:
    endpoint = Endpoint(type=EndpointType.IP, address="192.168.1.10")
    node = Node(name="INFRA-01", endpoints=[endpoint])
    runtime = NodeRuntime.from_node(node)

    assert runtime.get_endpoint_runtime(endpoint) is runtime.endpoint_runtimes[0]


def test_node_runtime_returns_none_for_unknown_endpoint_runtime() -> None:
    known_endpoint = Endpoint(type=EndpointType.IP, address="192.168.1.10")
    unknown_endpoint = Endpoint(type=EndpointType.IP, address="192.168.1.11")
    node = Node(name="INFRA-01", endpoints=[known_endpoint])
    runtime = NodeRuntime.from_node(node)

    assert runtime.get_endpoint_runtime(unknown_endpoint) is None


def test_node_runtime_can_get_service_runtime() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", services=[service])
    runtime = NodeRuntime.from_node(node)

    assert runtime.get_service_runtime(service) is runtime.service_runtimes[0]


def test_node_runtime_returns_none_for_unknown_service_runtime() -> None:
    known_service = Service(name="DNS", type=ServiceType.DNS)
    unknown_service = Service(name="MQTT", type=ServiceType.MQTT)
    node = Node(name="INFRA-01", services=[known_service])
    runtime = NodeRuntime.from_node(node)

    assert runtime.get_service_runtime(unknown_service) is None


def test_node_runtime_can_get_service_runtime_by_type() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", services=[service])
    runtime = NodeRuntime.from_node(node)

    assert (
        runtime.get_service_runtime_by_type(ServiceType.DNS)
        is (runtime.service_runtimes[0])
    )


def test_node_runtime_returns_none_for_unknown_service_runtime_type() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", services=[service])
    runtime = NodeRuntime.from_node(node)

    assert runtime.get_service_runtime_by_type(ServiceType.MQTT) is None
