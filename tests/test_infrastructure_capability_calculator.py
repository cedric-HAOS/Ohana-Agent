from ohana_agent.infrastructure import (
    HealthStatus,
    Infrastructure,
    InfrastructureCapability,
    InfrastructureCapabilityCalculator,
    InfrastructureRuntime,
    Node,
    Service,
    ServiceType,
)


def test_infrastructure_capability_can_be_created() -> None:
    capability = InfrastructureCapability(
        name="dns_available",
        available=True,
        health=HealthStatus.HEALTHY,
        reason="DNS is healthy.",
    )

    assert capability.name == "dns_available"
    assert capability.available is True
    assert capability.health is HealthStatus.HEALTHY
    assert capability.reason == "DNS is healthy."


def test_infrastructure_capability_calculator_can_be_created() -> None:
    infrastructure = Infrastructure(name="Ohana")
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    calculator = InfrastructureCapabilityCalculator(runtime=runtime)

    assert calculator.runtime is runtime


def test_calculate_dns_available_returns_unknown_when_dns_service_missing() -> None:
    infrastructure = Infrastructure(name="Ohana")
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    calculator = InfrastructureCapabilityCalculator(runtime=runtime)

    capability = calculator.calculate_dns_available()

    assert capability.name == "dns_available"
    assert capability.available is False
    assert capability.health is HealthStatus.UNKNOWN
    assert capability.reason == "No dns service runtime found."


def test_calculate_dns_available_returns_true_when_dns_is_healthy() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", services=[service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    service_runtime = runtime.get_service_runtime_by_type(ServiceType.DNS)
    calculator = InfrastructureCapabilityCalculator(runtime=runtime)

    assert service_runtime is not None

    service_runtime.update_health(HealthStatus.HEALTHY)

    capability = calculator.calculate_dns_available()

    assert capability.name == "dns_available"
    assert capability.available is True
    assert capability.health is HealthStatus.HEALTHY
    assert capability.reason == "dns service is healthy."


def test_calculate_dns_available_returns_false_when_dns_is_unhealthy() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", services=[service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    service_runtime = runtime.get_service_runtime_by_type(ServiceType.DNS)
    calculator = InfrastructureCapabilityCalculator(runtime=runtime)

    assert service_runtime is not None

    service_runtime.update_health(HealthStatus.UNHEALTHY)

    capability = calculator.calculate_dns_available()

    assert capability.name == "dns_available"
    assert capability.available is False
    assert capability.health is HealthStatus.UNHEALTHY
    assert capability.reason == "dns service is unhealthy."


def test_calculate_dns_available_returns_false_when_dns_is_degraded() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", services=[service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    service_runtime = runtime.get_service_runtime_by_type(ServiceType.DNS)
    calculator = InfrastructureCapabilityCalculator(runtime=runtime)

    assert service_runtime is not None

    service_runtime.update_health(HealthStatus.DEGRADED)

    capability = calculator.calculate_dns_available()

    assert capability.name == "dns_available"
    assert capability.available is False
    assert capability.health is HealthStatus.DEGRADED
    assert capability.reason == "dns service is degraded."


def test_calculate_mqtt_available_returns_unknown_when_mqtt_service_missing() -> None:
    infrastructure = Infrastructure(name="Ohana")
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    calculator = InfrastructureCapabilityCalculator(runtime=runtime)

    capability = calculator.calculate_mqtt_available()

    assert capability.name == "mqtt_available"
    assert capability.available is False
    assert capability.health is HealthStatus.UNKNOWN
    assert capability.reason == "No mqtt service runtime found."


def test_calculate_mqtt_available_returns_true_when_mqtt_is_healthy() -> None:
    service = Service(name="MQTT", type=ServiceType.MQTT)
    node = Node(name="INFRA-01", services=[service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    service_runtime = runtime.get_service_runtime_by_type(ServiceType.MQTT)
    calculator = InfrastructureCapabilityCalculator(runtime=runtime)

    assert service_runtime is not None

    service_runtime.update_health(HealthStatus.HEALTHY)

    capability = calculator.calculate_mqtt_available()

    assert capability.name == "mqtt_available"
    assert capability.available is True
    assert capability.health is HealthStatus.HEALTHY
    assert capability.reason == "mqtt service is healthy."


def test_calculate_mqtt_available_returns_false_when_mqtt_is_unhealthy() -> None:
    service = Service(name="MQTT", type=ServiceType.MQTT)
    node = Node(name="INFRA-01", services=[service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    service_runtime = runtime.get_service_runtime_by_type(ServiceType.MQTT)
    calculator = InfrastructureCapabilityCalculator(runtime=runtime)

    assert service_runtime is not None

    service_runtime.update_health(HealthStatus.UNHEALTHY)

    capability = calculator.calculate_mqtt_available()

    assert capability.name == "mqtt_available"
    assert capability.available is False
    assert capability.health is HealthStatus.UNHEALTHY
    assert capability.reason == "mqtt service is unhealthy."
