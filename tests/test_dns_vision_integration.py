from typing import Any

from ohana_agent.core.events import EventBus
from ohana_agent.infrastructure import (
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
    ObservationExportHandler,
    ObservationExportPipeline,
    ObservationPublished,
    ObserverResultMapper,
    PluginObservationExecutor,
)
from ohana_agent.observation.exporters import VisionObservationMapper
from ohana_agent.observation.exporters.vision_observation_exporter import (
    VisionObservationExporter,
)
from ohana_agent.plugins.dns.check_result import DNSCheckResult
from ohana_agent.plugins.dns.plugin import DNSPlugin
from ohana_agent.plugins.runtime.plugin_context import PluginContext
from ohana_agent.plugins.runtime.plugin_manager import PluginManager


class FakeDNSCheck:
    """Return a predefined DNS check result."""

    def __init__(self, result: DNSCheckResult) -> None:
        self.result = result
        self.hostnames: list[str] = []

    def check(self, hostname: str) -> DNSCheckResult:
        self.hostnames.append(hostname)
        return self.result


class FakeVisionClient:
    """Store observation payloads sent to Ohana-Vision."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def send_observation(
        self,
        payload: dict[str, Any],
    ) -> None:
        self.payloads.append(payload)


def make_plugin_context(event_bus: EventBus) -> PluginContext:
    """Build a plugin context for the integration test."""
    return PluginContext(
        event_bus=event_bus,
        scheduler=object(),
        dispatcher=object(),
        memory=object(),
        capability_manager=object(),
        configuration=object(),
        runtime=object(),
    )


def test_dns_observation_is_exported_to_vision_client() -> None:
    event_bus = EventBus()
    vision_client = FakeVisionClient()

    vision_exporter = VisionObservationExporter(
        client=vision_client,
        mapper=VisionObservationMapper(),
    )
    export_pipeline = ObservationExportPipeline(
        exporters=[vision_exporter],
    )
    export_handler = ObservationExportHandler(
        pipeline=export_pipeline,
    )

    event_bus.subscribe(
        ObservationPublished,
        export_handler.handle,
    )

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
        health_manager=InfrastructureHealthManager(
            runtime=runtime,
        ),
        mapper=InfrastructureObservationMapper(),
        result_mapper=ObserverResultMapper(),
        publisher=ObservationEventPublisher(
            event_publisher=event_bus,
        ),
    )

    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="example.com",
            healthy=True,
            address="93.184.216.34",
        )
    )
    dns_plugin = DNSPlugin(check=dns_check)

    plugin_manager = PluginManager(
        context=make_plugin_context(event_bus),
    )
    plugin_manager.register(dns_plugin)

    executor = PluginObservationExecutor(
        plugin_manager=plugin_manager,
        observation_engine=observation_engine,
    )

    event = executor.execute(
        "dns",
        target_name="dns",
        arguments={
            "hostname": "example.com",
        },
        source="dns.resolve",
    )

    assert dns_check.hostnames == ["example.com"]
    assert len(vision_client.payloads) == 1

    payload = vision_client.payloads[0]

    assert payload["node_id"] == "INFRA-01"
    assert payload["service_id"] == "dns-primary"
    assert payload["capability_id"] == "dns.resolve"
    assert payload["status"] == "healthy"
    assert payload["observed_at"] == (event.observation.timestamp.isoformat())
    assert payload["latency_ms"] == event.observation.latency_ms

    assert payload["metadata"] == {
        "hostname": "example.com",
        "server": None,
        "address": "93.184.216.34",
        "error": None,
        "agent_observation": {
            "id": str(event.observation.id),
            "source": "dns.resolve",
            "success": True,
            "message": ("DNS resolution succeeded for example.com."),
        },
    }
