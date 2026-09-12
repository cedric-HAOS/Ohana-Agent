from ohana_agent.infrastructure import (
    Endpoint,
    EndpointRuntime,
    EndpointType,
    HealthStatus,
)


def test_endpoint_runtime_can_be_created() -> None:
    endpoint = Endpoint(type=EndpointType.IP, address="192.168.1.10")
    runtime = EndpointRuntime(endpoint=endpoint)

    assert runtime.endpoint is endpoint
    assert runtime.health is HealthStatus.UNKNOWN
    assert runtime.last_update is None


def test_endpoint_runtime_can_update_health() -> None:
    endpoint = Endpoint(type=EndpointType.IP, address="192.168.1.10")
    runtime = EndpointRuntime(endpoint=endpoint)

    runtime.update_health(HealthStatus.HEALTHY)

    assert runtime.health is HealthStatus.HEALTHY
    assert runtime.last_update is not None
