from ohana_agent.infrastructure import (
    HealthStatus,
    Infrastructure,
    InfrastructureRuntime,
    Node,
    ObservationManager,
    SchedulerObservationHandler,
    Service,
    ServiceType,
)


def test_scheduler_observation_handler_can_be_created() -> None:
    infrastructure = Infrastructure(name="Ohana")
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    manager = ObservationManager(runtime=runtime)

    handler = SchedulerObservationHandler(observation_manager=manager)

    assert handler.observation_manager is manager


def test_scheduler_observation_handler_records_success() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    node = Node(name="INFRA-01", services=[service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    manager = ObservationManager(runtime=runtime)
    handler = SchedulerObservationHandler(observation_manager=manager)

    result = handler.handle_success(
        target_name="dns",
        source="scheduler",
        message="DNS check succeeded",
    )

    service_runtime = runtime.get_service_runtime_by_type(ServiceType.DNS)

    assert result is True
    assert len(manager.observations) == 1
    assert manager.observations[0].health is HealthStatus.HEALTHY
    assert manager.observations[0].message == "DNS check succeeded"
    assert service_runtime is not None
    assert service_runtime.health is HealthStatus.HEALTHY


def test_scheduler_observation_handler_records_failure() -> None:
    service = Service(name="MQTT", type=ServiceType.MQTT)
    node = Node(name="INFRA-01", services=[service])
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    manager = ObservationManager(runtime=runtime)
    handler = SchedulerObservationHandler(observation_manager=manager)

    result = handler.handle_failure(
        target_name="mqtt",
        source="scheduler",
        message="MQTT check failed",
    )

    service_runtime = runtime.get_service_runtime_by_type(ServiceType.MQTT)

    assert result is True
    assert len(manager.observations) == 1
    assert manager.observations[0].health is HealthStatus.UNHEALTHY
    assert manager.observations[0].message == "MQTT check failed"
    assert service_runtime is not None
    assert service_runtime.health is HealthStatus.UNHEALTHY


def test_scheduler_observation_handler_records_degraded() -> None:
    node = Node(name="INFRA-01")
    infrastructure = Infrastructure(name="Ohana", nodes=[node])
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    manager = ObservationManager(runtime=runtime)
    handler = SchedulerObservationHandler(observation_manager=manager)

    result = handler.handle_degraded(
        target_name="INFRA-01",
        source="scheduler",
        message="Node partially reachable",
    )

    node_runtime = runtime.get_node_runtime_by_name("INFRA-01")

    assert result is True
    assert len(manager.observations) == 1
    assert manager.observations[0].health is HealthStatus.DEGRADED
    assert manager.observations[0].message == "Node partially reachable"
    assert node_runtime is not None
    assert node_runtime.health is HealthStatus.DEGRADED


def test_scheduler_observation_handler_returns_false_for_unknown_target() -> None:
    infrastructure = Infrastructure(name="Ohana")
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    manager = ObservationManager(runtime=runtime)
    handler = SchedulerObservationHandler(observation_manager=manager)

    result = handler.handle_success(
        target_name="unknown",
        source="scheduler",
    )

    assert result is False
    assert len(manager.observations) == 1
