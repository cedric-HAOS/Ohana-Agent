import pytest

from infrastructure import (
    HealthStatus,
    Infrastructure,
    InfrastructureRuntime,
    Node,
    Service,
    ServiceType,
)
from infrastructure.infrastructure_health_update import (
    InfrastructureHealthUpdate,
)
from observer import (
    InfrastructureObservationMapper,
    ObservationStatus,
)


def test_mapper_converts_healthy_infrastructure_update() -> None:
    update = InfrastructureHealthUpdate(
        target_name="dns",
        health=HealthStatus.HEALTHY,
        source="dns.resolve",
        message="DNS resolution succeeded.",
        metadata={"server": "192.168.1.54"},
    )

    mapper = InfrastructureObservationMapper()

    observation = mapper.map(
        update,
        node="INFRA-01",
        service="dns",
        capability="dns.resolve",
        latency_ms=12.5,
    )

    assert observation.node == "INFRA-01"
    assert observation.service == "dns"
    assert observation.capability == "dns.resolve"
    assert observation.status is ObservationStatus.HEALTHY
    assert observation.success is True
    assert observation.message == "DNS resolution succeeded."
    assert observation.source == "dns.resolve"
    assert observation.latency_ms == 12.5
    assert observation.metadata == {"server": "192.168.1.54"}


def test_mapper_converts_unhealthy_infrastructure_update() -> None:
    update = InfrastructureHealthUpdate(
        target_name="dns",
        health=HealthStatus.UNHEALTHY,
        source="dns.resolve",
        message="DNS resolution failed.",
    )

    mapper = InfrastructureObservationMapper()

    observation = mapper.map(
        update,
        node="INFRA-01",
        service="dns",
        capability="dns.resolve",
    )

    assert observation.status is ObservationStatus.UNHEALTHY
    assert observation.success is False


def test_mapper_converts_degraded_infrastructure_update() -> None:
    update = InfrastructureHealthUpdate(
        target_name="mqtt",
        health=HealthStatus.DEGRADED,
        source="mqtt.connect",
    )

    mapper = InfrastructureObservationMapper()

    observation = mapper.map(
        update,
        node="HA-01",
        service="mqtt",
        capability="mqtt.connect",
    )

    assert observation.status is ObservationStatus.DEGRADED
    assert observation.success is False


def test_mapper_copies_update_metadata() -> None:
    update = InfrastructureHealthUpdate(
        target_name="dns",
        health=HealthStatus.HEALTHY,
        source="dns.resolve",
        metadata={"server": "192.168.1.54"},
    )

    mapper = InfrastructureObservationMapper()

    observation = mapper.map(
        update,
        node="INFRA-01",
        service="dns",
        capability="dns.resolve",
    )

    update.metadata["server"] = "8.8.8.8"

    assert observation.metadata == {"server": "192.168.1.54"}


def test_mapper_maps_service_update_from_runtime_context() -> None:
    service = Service(
        name="dns-primary",
        type=ServiceType.DNS,
    )
    node = Node(
        name="INFRA-01",
        services=[service],
    )
    infrastructure = Infrastructure(
        name="Ohana",
        nodes=[node],
    )
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    update = InfrastructureHealthUpdate(
        target_name="dns",
        health=HealthStatus.HEALTHY,
        source="dns.resolve",
        message="DNS resolution succeeded.",
        metadata={"server": "192.168.1.54"},
    )

    mapper = InfrastructureObservationMapper()

    observation = mapper.map_service_update(
        runtime,
        update,
        capability="dns.resolve",
        latency_ms=8.5,
    )

    assert observation.node == "INFRA-01"
    assert observation.service == "dns-primary"
    assert observation.capability == "dns.resolve"
    assert observation.status is ObservationStatus.HEALTHY
    assert observation.success is True
    assert observation.latency_ms == 8.5
    assert observation.metadata == {"server": "192.168.1.54"}


def test_mapper_rejects_unknown_service_target() -> None:
    infrastructure = Infrastructure(name="Ohana")
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    update = InfrastructureHealthUpdate(
        target_name="unknown-service",
        health=HealthStatus.UNKNOWN,
        source="test",
    )

    mapper = InfrastructureObservationMapper()

    with pytest.raises(
        ValueError,
        match="Unknown infrastructure service target",
    ):
        mapper.map_service_update(
            runtime,
            update,
            capability="unknown.check",
        )


def test_mapper_rejects_service_missing_from_runtime() -> None:
    infrastructure = Infrastructure(name="Ohana")
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)

    update = InfrastructureHealthUpdate(
        target_name="dns",
        health=HealthStatus.UNHEALTHY,
        source="dns.resolve",
    )

    mapper = InfrastructureObservationMapper()

    with pytest.raises(
        LookupError,
        match="No runtime found for service type",
    ):
        mapper.map_service_update(
            runtime,
            update,
            capability="dns.resolve",
        )


def test_mapper_targets_one_dns_service_by_stable_identifier() -> None:
    primary = Service(name="dns-primary", type=ServiceType.DNS)
    secondary = Service(name="dns-secondary", type=ServiceType.DNS)
    infrastructure = Infrastructure(
        name="Ohana",
        nodes=[
            Node(name="DNS-01", services=[primary]),
            Node(name="DNS-02", services=[secondary]),
        ],
    )
    runtime = InfrastructureRuntime.from_infrastructure(infrastructure)
    update = InfrastructureHealthUpdate(
        target_name="dns-secondary",
        health=HealthStatus.HEALTHY,
        source="dns.resolve",
    )

    observation = InfrastructureObservationMapper().map_service_update(
        runtime,
        update,
        capability="dns.resolve",
    )

    assert observation.node == "DNS-02"
    assert observation.service == "dns-secondary"
