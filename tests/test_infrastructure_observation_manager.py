from ohana_agent.infrastructure import (
    HealthStatus,
    Infrastructure,
    InfrastructureRuntime,
    Node,
    Observation,
    ObservationManager,
    Service,
    ServiceType,
)


def test_observation_manager_can_be_created() -> None:
    infrastructure = Infrastructure(name="Ohana")
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    manager = ObservationManager(runtime=runtime)

    assert manager.runtime is runtime
    assert manager.observations == []


def test_observation_manager_records_observation() -> None:
    infrastructure = Infrastructure(name="Ohana")
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    manager = ObservationManager(runtime=runtime)

    observation = Observation(
        target_name="unknown",
        health=HealthStatus.HEALTHY,
        source="test",
    )

    result = manager.record(observation)

    assert result is False
    assert manager.observations == [observation]


def test_observation_manager_applies_observation_to_service_runtime() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", services=[service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])

    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    manager = ObservationManager(runtime=runtime)

    observation = Observation(
        target_name="dns",
        health=HealthStatus.HEALTHY,
        source="dns-checker",
    )

    result = manager.record(observation)

    service_runtime = runtime.get_service_runtime_by_type(ServiceType.DNS)

    assert result is True
    assert service_runtime is not None
    assert service_runtime.health is HealthStatus.HEALTHY
    assert service_runtime.last_update is not None


def test_observation_manager_applies_observation_to_node_runtime() -> None:
    node = Node(name="INFRA-01")
    infrastructure = Infrastructure(
        name="Ohana",
        nodes=[node],
    )

    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    manager = ObservationManager(runtime=runtime)

    observation = Observation(
        target_name="INFRA-01",
        health=HealthStatus.DEGRADED,
        source="node-checker",
    )

    result = manager.record(observation)

    node_runtime = runtime.get_node_runtime_by_name("INFRA-01")

    assert result is True
    assert node_runtime is not None
    assert node_runtime.health is HealthStatus.DEGRADED
    assert node_runtime.last_update is not None


def test_observation_manager_returns_false_for_unknown_target() -> None:
    infrastructure = Infrastructure(name="Ohana")

    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    manager = ObservationManager(runtime=runtime)

    observation = Observation(
        target_name="missing",
        health=HealthStatus.UNHEALTHY,
        source="test",
    )

    assert manager.record(observation) is False
