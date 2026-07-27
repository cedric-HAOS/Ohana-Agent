"""Integration test from MQTT plugin execution to Vision export."""

from typing import Any

from core.events import EventBus
from infrastructure import (
    Infrastructure,
    InfrastructureRuntime,
    Node,
    Service,
    ServiceType,
)
from infrastructure.infrastructure_health_manager import InfrastructureHealthManager
from observer import (
    InfrastructureObservationMapper,
    ObservationEngine,
    ObservationEventPublisher,
    ObservationExportHandler,
    ObservationExportPipeline,
    ObservationPublished,
    ObserverResultMapper,
    PluginObservationExecutor,
)
from observer.exporters import VisionObservationMapper
from observer.exporters.vision_observation_exporter import VisionObservationExporter
from plugin.plugin_context import PluginContext
from plugin.plugin_manager import PluginManager
from plugins.mqtt.mqtt_check_result import MQTTCheckResult
from plugins.mqtt.mqtt_plugin import MQTTPlugin


class FakeMQTTCheck:
    def check(
        self,
        broker: str,
        **kwargs: object,
    ) -> MQTTCheckResult:
        return MQTTCheckResult(
            broker=broker,
            port=int(kwargs["port"]),
            healthy=True,
            topic="ohana/agent/check/mqtt-primary/token",
            qos=1,
            client_id="ohana-agent-mqtt-primary-token",
            connected=True,
            subscribed=True,
            published=True,
            received=True,
            round_trip_ms=9.5,
        )


class FakeVisionClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def send_observation(self, payload: dict[str, Any]) -> None:
        self.payloads.append(payload)


def test_mqtt_observation_is_exported_to_vision() -> None:
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
    service = Service(name="mqtt-primary", type=ServiceType.MQTT)
    runtime = InfrastructureRuntime.from_infrastructure(
        Infrastructure(
            name="Ohana",
            nodes=[Node(name="ha-01", services=[service])],
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
    manager.register(MQTTPlugin(check=FakeMQTTCheck()))

    PluginObservationExecutor(
        plugin_manager=manager,
        observation_engine=engine,
    ).execute(
        "mqtt",
        target_name="mqtt-primary",
        arguments={
            "broker": "192.168.1.247",
            "port": 1883,
            "service_id": "mqtt-primary",
        },
        source="mqtt.roundtrip",
    )

    assert len(vision_client.payloads) == 1
    payload = vision_client.payloads[0]
    assert payload["node_id"] == "ha-01"
    assert payload["service_id"] == "mqtt-primary"
    assert payload["capability_id"] == "mqtt.roundtrip"
    assert payload["status"] == "healthy"
    assert payload["latency_ms"] == 9.5
    assert payload["metadata"]["received"] is True
    assert payload["metadata"]["qos"] == 1
