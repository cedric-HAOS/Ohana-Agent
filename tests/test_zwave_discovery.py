"""Tests for dynamic Z-Wave node projection."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from infrastructure.enums import HealthStatus
from plugins.zwave.zwave_discovery import ZWaveDiscoveryHandler


@dataclass
class FakeObservationEngine:
    calls: list[tuple[Any, str, str]] = field(default_factory=list)

    def process_result(
        self,
        result: Any,
        *,
        target_name: str,
        source: str,
    ) -> None:
        self.calls.append((result, target_name, source))


def controller_event(
    *,
    service_id: str = "zwave-main",
    metadata: dict[str, Any],
) -> Any:
    return SimpleNamespace(
        observation=SimpleNamespace(
            capability="zwave.status",
            service=service_id,
            timestamp=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
            metadata=metadata,
        )
    )


def base_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "services": [
            {
                "service_id": "zwave-main",
                "node_id": "zwave-01",
            }
        ],
        "topology": {
            "devices": [
                {
                    "device_id": "rpi-zwave",
                    "label": "RPI-ZWAVE",
                    "kind": "raspberry_pi",
                    "node_id": "zwave-01",
                    "metadata": {"role": "zwave_gateway"},
                },
                {
                    "device_id": "manual-device",
                    "label": "Manuel",
                    "kind": "smart_device",
                    "node_id": None,
                    "metadata": {},
                },
            ],
            "links": [],
            "layouts": [],
            "metadata": {},
        },
    }


def test_discovery_adds_nodes_and_gateway_links_only() -> None:
    holder = {"payload": base_payload()}
    updates: list[dict[str, Any]] = []
    engine = FakeObservationEngine()

    def update(payload: dict[str, Any]) -> None:
        holder["payload"] = payload
        updates.append(payload)

    handler = ZWaveDiscoveryHandler(
        observation_engine=engine,  # type: ignore[arg-type]
        infrastructure_payload=lambda: holder["payload"],
        update_infrastructure=update,
    )
    handler.handle(
        controller_event(
            metadata={
                "discovery_complete": True,
                "home_id": "305419896",
                "nodes": [
                    {
                        "node_id": 2,
                        "status": "awake",
                        "name": "Porte entree",
                        "can_sleep": True,
                    },
                    {
                        "node_id": 3,
                        "status": "dead",
                        "label": "Prise garage",
                    },
                ],
            }
        )
    )

    assert len(updates) == 1
    topology = updates[0]["topology"]
    discovered = [
        device
        for device in topology["devices"]
        if device["metadata"].get("managed_by") == "zwave_discovery"
    ]
    assert [device["device_id"] for device in discovered] == [
        "zwave-zwave-main-node-2",
        "zwave-zwave-main-node-3",
    ]
    assert discovered[0]["label"] == "Porte entree"
    assert discovered[0]["node_id"] is None
    assert all(link["source_device_id"] == "rpi-zwave" for link in topology["links"])
    assert {link["target_device_id"] for link in topology["links"]} == {
        "zwave-zwave-main-node-2",
        "zwave-zwave-main-node-3",
    }
    assert all(link["kind"] == "zwave" for link in topology["links"])
    assert all(
        link["source_device_id"]
        not in {
            "zwave-zwave-main-node-2",
            "zwave-zwave-main-node-3",
        }
        for link in topology["links"]
    )

    assert [call[1] for call in engine.calls] == [
        "zwave-zwave-main-node-2",
        "zwave-zwave-main-node-3",
    ]
    assert [call[0].health for call in engine.calls] == [
        HealthStatus.HEALTHY,
        HealthStatus.UNHEALTHY,
    ]
    assert all(call[2] == "zwave.node.alive" for call in engine.calls)
    assert all(
        call[0].metadata["contributes_to_device_health"] is True
        for call in engine.calls
    )


def test_sleeping_node_is_alive() -> None:
    holder = {"payload": base_payload()}
    engine = FakeObservationEngine()
    handler = ZWaveDiscoveryHandler(
        observation_engine=engine,  # type: ignore[arg-type]
        infrastructure_payload=lambda: holder["payload"],
        update_infrastructure=lambda payload: holder.update(payload=payload),
    )

    handler.handle(
        controller_event(
            metadata={
                "discovery_complete": True,
                "nodes": [{"node_id": 8, "status": "asleep"}],
            }
        )
    )

    result = engine.calls[0][0]
    assert result.health is HealthStatus.HEALTHY
    assert result.success is True
    assert "endormi et vivant" in result.message


def test_controller_failure_marks_known_nodes_unknown_without_removing_them() -> None:
    payload = base_payload()
    payload["topology"]["devices"].append(
        {
            "device_id": "zwave-zwave-main-node-4",
            "label": "Z-Wave 4",
            "kind": "smart_device",
            "node_id": None,
            "metadata": {
                "managed_by": "zwave_discovery",
                "controller_service_id": "zwave-main",
            },
        }
    )
    updates: list[dict[str, Any]] = []
    engine = FakeObservationEngine()
    handler = ZWaveDiscoveryHandler(
        observation_engine=engine,  # type: ignore[arg-type]
        infrastructure_payload=lambda: payload,
        update_infrastructure=updates.append,
    )

    handler.handle(
        controller_event(
            metadata={
                "discovery_complete": False,
                "nodes": [],
            }
        )
    )

    assert updates == []
    assert len(engine.calls) == 1
    assert engine.calls[0][1] == "zwave-zwave-main-node-4"
    assert engine.calls[0][0].health is HealthStatus.UNKNOWN


def test_discovery_reconciles_removed_nodes_and_preserves_manual_devices() -> None:
    holder = {"payload": base_payload()}
    engine = FakeObservationEngine()
    handler = ZWaveDiscoveryHandler(
        observation_engine=engine,  # type: ignore[arg-type]
        infrastructure_payload=lambda: holder["payload"],
        update_infrastructure=lambda payload: holder.update(payload=payload),
    )
    handler.handle(
        controller_event(
            metadata={
                "discovery_complete": True,
                "nodes": [
                    {"node_id": 2, "status": "alive"},
                    {"node_id": 3, "status": "alive"},
                ],
            }
        )
    )
    handler.handle(
        controller_event(
            metadata={
                "discovery_complete": True,
                "nodes": [{"node_id": 3, "status": "alive"}],
            }
        )
    )

    device_ids = {
        device["device_id"] for device in holder["payload"]["topology"]["devices"]
    }
    assert "manual-device" in device_ids
    assert "zwave-zwave-main-node-2" not in device_ids
    assert "zwave-zwave-main-node-3" in device_ids
