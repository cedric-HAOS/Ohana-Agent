"""Integration test from NTP plugin execution to Vision export."""

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
from ohana_agent.plugins.ntp.check_result import NTPCheckResult
from ohana_agent.plugins.ntp.plugin import NTPPlugin
from ohana_agent.plugins.runtime.plugin_context import PluginContext
from ohana_agent.plugins.runtime.plugin_manager import PluginManager


class FakeNTPCheck:
    def check(
        self,
        server: str,
        *,
        port: int,
        timeout: float,
        retries: int,
    ) -> NTPCheckResult:
        del timeout, retries
        return NTPCheckResult(
            server=server,
            port=port,
            healthy=True,
            source_address=server,
            offset_ms=1.5,
            round_trip_ms=6.0,
            stratum=3,
            version=4,
            leap_indicator=0,
        )


class FakeVisionClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def send_observation(self, payload: dict[str, Any]) -> None:
        self.payloads.append(payload)


def test_ntp_observation_is_exported_to_vision() -> None:
    event_bus = EventBus()
    vision_client = FakeVisionClient()
    event_bus.subscribe(
        ObservationPublished,
        ObservationExportHandler(
            pipeline=ObservationExportPipeline(
                exporters=[
                    VisionObservationExporter(
                        client=vision_client,
                        mapper=VisionObservationMapper(),
                    )
                ]
            )
        ).handle,
    )
    service = Service(name="ntp-primary", type=ServiceType.NTP)
    runtime = InfrastructureRuntime.from_infrastructure(
        Infrastructure(
            name="Ohana",
            nodes=[Node(name="infra-01", services=[service])],
        )
    )
    engine = ObservationEngine(
        health_manager=InfrastructureHealthManager(runtime=runtime),
        mapper=InfrastructureObservationMapper(),
        result_mapper=ObserverResultMapper(),
        publisher=ObservationEventPublisher(event_publisher=event_bus),
    )
    manager = PluginManager(
        context=PluginContext(
            event_bus=event_bus,
            scheduler=None,
            dispatcher=None,
            memory=None,
            capability_manager=None,
            configuration=None,
            runtime=runtime,
        )
    )
    manager.register(NTPPlugin(check=FakeNTPCheck()))

    PluginObservationExecutor(
        plugin_manager=manager,
        observation_engine=engine,
    ).execute(
        "ntp",
        target_name="ntp-primary",
        arguments={"server": "192.168.1.10", "port": 123},
        source="ntp.query",
    )

    assert len(vision_client.payloads) == 1
    payload = vision_client.payloads[0]
    assert payload["node_id"] == "infra-01"
    assert payload["service_id"] == "ntp-primary"
    assert payload["capability_id"] == "ntp.query"
    assert payload["status"] == "healthy"
    assert payload["latency_ms"] == 6.0
    assert payload["metadata"]["offset_ms"] == 1.5
    assert payload["metadata"]["stratum"] == 3
