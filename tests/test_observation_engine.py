from dataclasses import dataclass, field

import pytest

from infrastructure import (
    HealthStatus,
    Infrastructure,
    InfrastructureRuntime,
    Node,
    Service,
    ServiceType,
)
from infrastructure.infrastructure_health_manager import (
    InfrastructureHealthManager,
)
from infrastructure.infrastructure_health_update import (
    InfrastructureHealthUpdate,
)
from observer import (
    InfrastructureObservationMapper,
    ObservationEngine,
    ObservationEventPublisher,
    ObservationPublished,
    ObservationStatus,
    ObserverResult,
    ObserverResultMapper,
)


@dataclass
class FakeEventPublisher:
    """Fake domain event publisher used by engine tests."""

    events: list[object] = field(default_factory=list)

    def publish(self, event: object) -> None:
        """Store a published event."""
        self.events.append(event)


def build_engine() -> tuple[
    ObservationEngine,
    InfrastructureRuntime,
    FakeEventPublisher,
]:
    """Build an observation engine with a DNS infrastructure."""
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

    health_manager = InfrastructureHealthManager(runtime=runtime)
    mapper = InfrastructureObservationMapper()
    event_publisher = FakeEventPublisher()
    publisher = ObservationEventPublisher(
        event_publisher=event_publisher,
    )
    result_mapper = ObserverResultMapper()

    engine = ObservationEngine(
        health_manager=health_manager,
        mapper=mapper,
        publisher=publisher,
        result_mapper=result_mapper,
    )

    return engine, runtime, event_publisher


def test_observation_engine_processes_service_update() -> None:
    engine, runtime, _ = build_engine()

    update = InfrastructureHealthUpdate(
        target_name="dns",
        health=HealthStatus.HEALTHY,
        source="dns.resolve",
        message="DNS resolution succeeded.",
        metadata={"server": "192.168.1.54"},
    )

    event = engine.process_service_update(
        update,
        capability="dns.resolve",
        latency_ms=12.5,
    )

    service_runtime = runtime.get_service_runtime_by_type(ServiceType.DNS)

    assert service_runtime is not None
    assert service_runtime.health is HealthStatus.HEALTHY
    assert isinstance(event, ObservationPublished)
    assert event.observation.node == "INFRA-01"
    assert event.observation.service == "dns-primary"
    assert event.observation.capability == "dns.resolve"
    assert event.observation.status is ObservationStatus.HEALTHY
    assert event.observation.success is True
    assert event.observation.latency_ms == 12.5
    assert event.observation.metadata == {
        "server": "192.168.1.54",
    }


def test_observation_engine_records_health_update() -> None:
    engine, _, _ = build_engine()

    update = InfrastructureHealthUpdate(
        target_name="dns",
        health=HealthStatus.DEGRADED,
        source="dns.resolve",
    )

    engine.process_service_update(
        update,
        capability="dns.resolve",
    )

    assert engine.health_manager.observations == [update]


def test_observation_engine_publishes_observation_event() -> None:
    engine, _, event_publisher = build_engine()

    update = InfrastructureHealthUpdate(
        target_name="dns",
        health=HealthStatus.UNHEALTHY,
        source="dns.resolve",
        message="DNS resolution failed.",
    )

    event = engine.process_service_update(
        update,
        capability="dns.resolve",
    )

    assert event_publisher.events == [event]
    assert event.observation.status is ObservationStatus.UNHEALTHY
    assert event.observation.success is False


def test_observation_engine_rejects_unapplicable_update() -> None:
    engine, _, event_publisher = build_engine()

    update = InfrastructureHealthUpdate(
        target_name="mqtt",
        health=HealthStatus.UNHEALTHY,
        source="mqtt.connect",
    )

    with pytest.raises(
        LookupError,
        match="Unable to apply infrastructure health update",
    ):
        engine.process_service_update(
            update,
            capability="mqtt.connect",
        )

    assert event_publisher.events == []


def test_observation_engine_processes_observer_result() -> None:
    engine, runtime, _ = build_engine()

    result = ObserverResult(
        success=True,
        latency=7.5,
        message="DNS resolution succeeded.",
        check="dns.resolve",
        metadata={"server": "192.168.1.54"},
    )

    event = engine.process_result(
        result,
        target_name="dns",
    )

    service_runtime = runtime.get_service_runtime_by_type(ServiceType.DNS)

    assert service_runtime is not None
    assert service_runtime.health is HealthStatus.HEALTHY
    assert event.observation.node == "INFRA-01"
    assert event.observation.service == "dns-primary"
    assert event.observation.capability == "dns.resolve"
    assert event.observation.status is ObservationStatus.HEALTHY
    assert event.observation.success is True
    assert event.observation.latency_ms == 7.5
    assert event.observation.metadata == {
        "server": "192.168.1.54",
    }


def test_observation_engine_processes_failed_observer_result() -> None:
    engine, runtime, event_publisher = build_engine()

    result = ObserverResult(
        success=False,
        latency=0.0,
        message="DNS resolution failed.",
        check="dns.resolve",
    )

    event = engine.process_result(
        result,
        target_name="dns",
    )

    service_runtime = runtime.get_service_runtime_by_type(ServiceType.DNS)

    assert service_runtime is not None
    assert service_runtime.health is HealthStatus.UNHEALTHY
    assert event.observation.status is ObservationStatus.UNHEALTHY
    assert event.observation.success is False
    assert event_publisher.events == [event]


def test_observation_engine_process_result_uses_explicit_source() -> None:
    engine, _, _ = build_engine()

    result = ObserverResult(
        success=True,
        latency=1.0,
        check=None,
    )

    event = engine.process_result(
        result,
        target_name="dns",
        source="dns.custom",
    )

    assert event.observation.source == "dns.custom"
    assert event.observation.capability == "dns.custom"


def test_observation_engine_updates_dns_service_by_identifier() -> None:
    primary = Service(name="dns-primary", type=ServiceType.DNS)
    secondary = Service(name="dns-secondary", type=ServiceType.DNS)
    runtime = InfrastructureRuntime.from_infrastructure(
        Infrastructure(
            name="Ohana",
            nodes=[
                Node(name="DNS-01", services=[primary]),
                Node(name="DNS-02", services=[secondary]),
            ],
        )
    )
    engine = ObservationEngine(
        health_manager=InfrastructureHealthManager(runtime=runtime),
        mapper=InfrastructureObservationMapper(),
        result_mapper=ObserverResultMapper(),
        publisher=ObservationEventPublisher(
            event_publisher=FakeEventPublisher(),
        ),
    )

    event = engine.process_result(
        ObserverResult(success=True, latency=1.0, check="dns.resolve"),
        target_name="dns-secondary",
    )

    primary_runtime = runtime.get_service_runtime_by_name("dns-primary")
    secondary_runtime = runtime.get_service_runtime_by_name("dns-secondary")

    assert primary_runtime is not None
    assert secondary_runtime is not None
    assert primary_runtime.health is HealthStatus.UNKNOWN
    assert secondary_runtime.health is HealthStatus.HEALTHY
    assert event.observation.service == "dns-secondary"
    assert event.observation.node == "DNS-02"


def test_observation_engine_publishes_device_presence_without_global_health() -> None:
    engine, runtime, event_publisher = build_engine()
    service_runtime = runtime.get_service_runtime_by_type(ServiceType.DNS)

    assert service_runtime is not None
    assert service_runtime.health is HealthStatus.UNKNOWN

    result = ObserverResult(
        success=False,
        latency=0.0,
        health=HealthStatus.UNKNOWN,
        check="network.reachable",
        message="INFRA-01 did not respond (1/3 failed checks).",
        metadata={
            "target_type": "device",
            "device_id": "infra-01",
            "node_id": "INFRA-01",
            "address": "192.168.1.10",
        },
    )

    event = engine.process_result(
        result,
        target_name="infra-01",
    )

    assert service_runtime.health is HealthStatus.UNKNOWN
    assert engine.health_manager.observations == []
    assert event.observation.node == "INFRA-01"
    assert event.observation.service == "infra-01"
    assert event.observation.capability == "network.reachable"
    assert event.observation.status is ObservationStatus.UNKNOWN
    assert event.observation.metadata["device_id"] == "infra-01"
    assert event_publisher.events == [event]
