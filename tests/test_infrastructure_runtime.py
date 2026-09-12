from ohana_agent.infrastructure import (
    Endpoint,
    EndpointType,
    HealthStatus,
    Infrastructure,
    InfrastructureRuntime,
    Node,
    Service,
    ServiceType,
)


def test_infrastructure_runtime_can_be_created() -> None:
    infrastructure = Infrastructure(name="Ohana")
    runtime = InfrastructureRuntime(infrastructure=infrastructure)

    assert runtime.infrastructure is infrastructure
    assert runtime.health is HealthStatus.UNKNOWN
    assert runtime.node_runtimes == []
    assert runtime.last_update is None


def test_infrastructure_runtime_can_update_health() -> None:
    infrastructure = Infrastructure(name="Ohana")
    runtime = InfrastructureRuntime(infrastructure=infrastructure)

    runtime.update_health(HealthStatus.HEALTHY)

    assert runtime.health is HealthStatus.HEALTHY
    assert runtime.last_update is not None


def test_infrastructure_runtime_can_be_created_from_infrastructure() -> None:
    node = Node(name="INFRA-01")
    infrastructure = Infrastructure(name="Ohana", nodes=[node])

    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    assert runtime.infrastructure is infrastructure
    assert len(runtime.node_runtimes) == 1
    assert runtime.node_runtimes[0].node is node


def test_infrastructure_runtime_from_infrastructure_creates_nested_runtimes() -> None:
    endpoint = Endpoint(type=EndpointType.IP, address="192.168.1.10")
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", endpoints=[endpoint], services=[service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])

    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    node_runtime = runtime.node_runtimes[0]

    assert node_runtime.endpoint_runtimes[0].endpoint is endpoint
    assert node_runtime.service_runtimes[0].service is service


def test_infrastructure_runtime_can_get_node_runtime() -> None:
    node = Node(name="INFRA-01")
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    assert runtime.get_node_runtime(node) is runtime.node_runtimes[0]


def test_infrastructure_runtime_returns_none_for_unknown_node_runtime() -> None:
    known_node = Node(name="INFRA-01")
    unknown_node = Node(name="INFRA-02")
    infrastructure = Infrastructure(name="Ohana", nodes=[known_node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    assert runtime.get_node_runtime(unknown_node) is None


def test_infrastructure_runtime_can_get_node_runtime_by_name() -> None:
    node = Node(name="INFRA-01")
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    assert runtime.get_node_runtime_by_name("INFRA-01") is runtime.node_runtimes[0]


def test_infrastructure_runtime_returns_none_for_unknown_node_runtime_name() -> None:
    infrastructure = Infrastructure(name="Ohana")
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    assert runtime.get_node_runtime_by_name("UNKNOWN") is None


def test_infrastructure_runtime_can_get_service_runtime() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", services=[service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    assert (
        runtime.get_service_runtime(service)
        is (runtime.node_runtimes[0].service_runtimes[0])
    )


def test_infrastructure_runtime_returns_none_for_unknown_service_runtime() -> None:
    known_service = Service(name="DNS", type=ServiceType.DNS)
    unknown_service = Service(name="MQTT", type=ServiceType.MQTT)
    node = Node(name="INFRA-01", services=[known_service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    assert runtime.get_service_runtime(unknown_service) is None


def test_infrastructure_runtime_can_get_service_runtime_by_type() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", services=[service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    assert (
        runtime.get_service_runtime_by_type(ServiceType.DNS)
        is (runtime.node_runtimes[0].service_runtimes[0])
    )


def test_infrastructure_runtime_returns_none_for_unknown_service_runtime_type() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", services=[service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    assert runtime.get_service_runtime_by_type(ServiceType.MQTT) is None


def test_infrastructure_runtime_can_get_node_runtime_for_service() -> None:
    dns_service = Service(name="DNS", type=ServiceType.DNS)
    mqtt_service = Service(name="MQTT", type=ServiceType.MQTT)

    dns_node = Node(name="INFRA-01", services=[dns_service])
    mqtt_node = Node(name="HA-01", services=[mqtt_service])

    infrastructure = Infrastructure(
        name="Ohana",
        nodes=[dns_node, mqtt_node],
    )
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    node_runtime = runtime.get_node_runtime_for_service(mqtt_service)

    assert node_runtime is runtime.node_runtimes[1]
    assert node_runtime.node is mqtt_node


def test_infrastructure_runtime_returns_none_for_unknown_service_owner() -> None:
    known_service = Service(name="DNS", type=ServiceType.DNS)
    unknown_service = Service(name="MQTT", type=ServiceType.MQTT)

    node = Node(name="INFRA-01", services=[known_service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    assert runtime.get_node_runtime_for_service(unknown_service) is None


def test_infrastructure_runtime_can_get_node_runtime_for_service_type() -> None:
    dns_service = Service(name="DNS", type=ServiceType.DNS)
    mqtt_service = Service(name="MQTT", type=ServiceType.MQTT)

    dns_node = Node(name="INFRA-01", services=[dns_service])
    mqtt_node = Node(name="HA-01", services=[mqtt_service])

    infrastructure = Infrastructure(
        name="Ohana",
        nodes=[dns_node, mqtt_node],
    )
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    node_runtime = runtime.get_node_runtime_for_service_type(ServiceType.MQTT)

    assert node_runtime is runtime.node_runtimes[1]
    assert node_runtime.node is mqtt_node


def test_infrastructure_runtime_returns_none_for_unknown_service_type_owner() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", services=[service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    node_runtime = runtime.get_node_runtime_for_service_type(ServiceType.MQTT)

    assert node_runtime is None
