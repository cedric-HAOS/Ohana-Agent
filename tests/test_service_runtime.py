from ohana_agent.infrastructure import (
    HealthStatus,
    Service,
    ServiceRuntime,
    ServiceType,
)


def test_service_runtime_can_be_created() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    runtime = ServiceRuntime(service=service)

    assert runtime.service is service
    assert runtime.health is HealthStatus.UNKNOWN
    assert runtime.last_update is None


def test_service_runtime_can_update_health() -> None:
    service = Service(name="DNS", type=ServiceType.DNS)
    runtime = ServiceRuntime(service=service)

    runtime.update_health(HealthStatus.HEALTHY)

    assert runtime.health is HealthStatus.HEALTHY
    assert runtime.last_update is not None
