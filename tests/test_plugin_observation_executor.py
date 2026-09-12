from dataclasses import dataclass, field
from typing import Any

import pytest

from ohana_agent.infrastructure import (
    HealthStatus,
    Infrastructure,
    InfrastructureRuntime,
    Node,
    Service,
    ServiceType,
)
from ohana_agent.infrastructure.infrastructure_health_manager import (
    InfrastructureHealthManager,
)
from ohana_agent.observation import (
    InfrastructureObservationMapper,
    ObservationEngine,
    ObservationEventPublisher,
    ObservationStatus,
    ObserverResult,
    ObserverResultMapper,
)
from ohana_agent.observation.plugin_observation_executor import (
    PluginObservationExecutor,
)
from ohana_agent.plugins.runtime import (
    PluginManager,
    PluginManifest,
    PluginNotFoundError,
)
from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_command import PluginCommand
from ohana_agent.plugins.runtime.plugin_context import PluginContext


@dataclass
class FakeEventBus:
    """Store published domain events."""

    events: list[object] = field(default_factory=list)

    def publish(self, event: object) -> None:
        self.events.append(event)


class FakePlugin(Plugin):
    """Plugin used to test execution through the observation bridge."""

    def __init__(self, result: ObserverResult) -> None:
        self._result = result
        self.registered_context: PluginContext | None = None
        self.received_arguments: dict[str, Any] | None = None

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name="dns",
            version="1.0.0",
        )

    def register(self, context: PluginContext) -> None:
        self.registered_context = context

    def execute(self, **kwargs: Any) -> ObserverResult:
        self.received_arguments = kwargs
        return self._result


def build_executor(
    result: ObserverResult,
) -> tuple[
    PluginObservationExecutor,
    FakePlugin,
    InfrastructureRuntime,
    FakeEventBus,
]:
    """Build a plugin-to-observation execution pipeline."""
    event_bus = FakeEventBus()

    context = PluginContext(
        event_bus=event_bus,
        scheduler=object(),
        dispatcher=object(),
        memory=object(),
        capability_manager=object(),
        configuration=object(),
        runtime=object(),
    )

    plugin = FakePlugin(result)
    plugin_manager = PluginManager(context=context)
    plugin_manager.register(plugin)

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

    observation_engine = ObservationEngine(
        health_manager=InfrastructureHealthManager(runtime=runtime),
        mapper=InfrastructureObservationMapper(),
        result_mapper=ObserverResultMapper(),
        publisher=ObservationEventPublisher(
            event_publisher=event_bus,
        ),
    )

    executor = PluginObservationExecutor(
        plugin_manager=plugin_manager,
        observation_engine=observation_engine,
    )

    return executor, plugin, runtime, event_bus


def test_executor_executes_registered_plugin() -> None:
    result = ObserverResult(
        success=True,
        latency=4.5,
        check="dns.resolve",
        message="DNS resolution succeeded.",
    )
    executor, plugin, _, _ = build_executor(result)

    executor.execute(
        "dns",
        target_name="dns",
        arguments={"hostname": "example.com"},
    )

    assert plugin.received_arguments == {
        "hostname": "example.com",
    }


def test_executor_processes_plugin_result() -> None:
    result = ObserverResult(
        success=True,
        latency=4.5,
        check="dns.resolve",
        message="DNS resolution succeeded.",
        metadata={"address": "93.184.216.34"},
    )
    executor, _, runtime, _ = build_executor(result)

    event = executor.execute(
        "dns",
        target_name="dns",
        arguments={"hostname": "example.com"},
    )

    service_runtime = runtime.get_service_runtime_by_type(ServiceType.DNS)

    assert service_runtime is not None
    assert service_runtime.health is HealthStatus.HEALTHY
    assert event.observation.node == "INFRA-01"
    assert event.observation.service == "dns-primary"
    assert event.observation.capability == "dns.resolve"
    assert event.observation.status is ObservationStatus.HEALTHY
    assert event.observation.latency_ms == 4.5
    assert event.observation.metadata == {
        "address": "93.184.216.34",
    }


def test_executor_publishes_observation_event() -> None:
    result = ObserverResult(
        success=False,
        latency=0.0,
        check="dns.resolve",
        message="DNS resolution failed.",
    )
    executor, _, _, event_bus = build_executor(result)

    event = executor.execute(
        "dns",
        target_name="dns",
    )

    assert event_bus.events[-1] is event
    assert event.observation.status is ObservationStatus.UNHEALTHY


def test_executor_rejects_unknown_plugin() -> None:
    result = ObserverResult(
        success=True,
        latency=1.0,
        check="dns.resolve",
    )
    executor, _, _, _ = build_executor(result)

    with pytest.raises(
        PluginNotFoundError,
        match="Plugin not found",
    ):
        executor.execute(
            "unknown",
            target_name="dns",
        )


def test_executor_executes_structured_plugin_command() -> None:
    result = ObserverResult(
        success=True,
        latency=3.5,
        check="dns.resolve",
        message="DNS resolution succeeded.",
    )
    executor, plugin, _, _ = build_executor(result)

    command = PluginCommand(
        plugin_name="dns",
        operation="resolve",
        target_name="dns",
        arguments={
            "hostname": "example.com",
        },
    )

    event = executor.execute_command(command)

    assert plugin.received_arguments == {
        "hostname": "example.com",
    }
    assert event.observation.service == "dns-primary"
    assert event.observation.capability == "dns.resolve"
    assert event.observation.source == "dns.resolve"
