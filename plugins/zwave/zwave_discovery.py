"""Project Z-Wave JS discoveries into Vision topology and observations."""

from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from infrastructure.enums import HealthStatus
from observer.events import ObservationPublished
from observer.observation_engine import ObservationEngine
from observer.observer_result import ObserverResult

_MANAGED_BY = "zwave_discovery"
_NODE_CAPABILITY = "zwave.node.alive"


@dataclass(slots=True)
class ZWaveDiscoveryHandler:
    """Keep discovered Z-Wave nodes in topology and publish their state."""

    observation_engine: ObservationEngine
    infrastructure_payload: Callable[[], dict[str, Any] | None]
    update_infrastructure: Callable[[dict[str, Any]], None]

    def handle(self, event: ObservationPublished) -> None:
        """Handle the controller observation produced by the Z-Wave plugin."""
        observation = event.observation

        if observation.capability != "zwave.status":
            return

        metadata = observation.metadata
        service_id = observation.service

        if metadata.get("discovery_complete") is True:
            nodes = self._valid_nodes(metadata.get("nodes"))
            self._synchronize_topology(
                service_id=service_id,
                home_id=self._optional_text(metadata.get("home_id")),
                nodes=nodes,
            )
            self._publish_node_states(
                service_id=service_id,
                home_id=self._optional_text(metadata.get("home_id")),
                nodes=nodes,
                observed_at=observation.timestamp,
            )
            return

        self._publish_unavailable_discovery(
            service_id=service_id,
            observed_at=observation.timestamp,
        )

    def _synchronize_topology(
        self,
        *,
        service_id: str,
        home_id: str | None,
        nodes: list[dict[str, Any]],
    ) -> None:
        current = self.infrastructure_payload()

        if current is None:
            return

        updated = deepcopy(current)
        topology = updated.setdefault(
            "topology",
            {"devices": [], "links": [], "layouts": [], "metadata": {}},
        )
        devices = topology.setdefault("devices", [])
        links = topology.setdefault("links", [])
        topology.setdefault("layouts", [])
        topology.setdefault("metadata", {})

        devices[:] = [
            device
            for device in devices
            if not self._is_managed(device, service_id=service_id)
        ]
        links[:] = [
            link for link in links if not self._is_managed(link, service_id=service_id)
        ]

        gateway_device_id = self._gateway_device_id(
            updated,
            service_id=service_id,
        )

        for node in nodes:
            device_id = self._device_id(service_id, int(node["node_id"]))
            devices.append(
                self._topology_device(
                    device_id=device_id,
                    service_id=service_id,
                    home_id=home_id,
                    node=node,
                )
            )

            if gateway_device_id is not None:
                links.append(
                    {
                        "link_id": f"{gateway_device_id}-{device_id}",
                        "source_device_id": gateway_device_id,
                        "target_device_id": device_id,
                        "kind": "zwave",
                        "direction": "bidirectional",
                        "label": "Z-Wave",
                        "bandwidth_mbps": None,
                        "metadata": {
                            "managed_by": _MANAGED_BY,
                            "controller_service_id": service_id,
                        },
                    }
                )

        if updated != current:
            self.update_infrastructure(updated)

    def _publish_node_states(
        self,
        *,
        service_id: str,
        home_id: str | None,
        nodes: list[dict[str, Any]],
        observed_at: Any,
    ) -> None:
        for node in nodes:
            node_id = int(node["node_id"])
            device_id = self._device_id(service_id, node_id)
            status = str(node.get("status") or "unknown").strip().lower()
            health = self._health(status)
            label = self._node_label(node)

            self.observation_engine.process_result(
                ObserverResult(
                    success=health is HealthStatus.HEALTHY,
                    latency=0.0,
                    timestamp=observed_at,
                    message=self._state_message(label, status),
                    check=_NODE_CAPABILITY,
                    description="Etat vivant du noeud Z-Wave.",
                    metadata={
                        "target_type": "device",
                        "device_id": device_id,
                        "contributes_to_device_health": True,
                        "controller_service_id": service_id,
                        "home_id": home_id,
                        **node,
                    },
                    health=health,
                ),
                target_name=device_id,
                source=_NODE_CAPABILITY,
            )

    def _publish_unavailable_discovery(
        self,
        *,
        service_id: str,
        observed_at: Any,
    ) -> None:
        current = self.infrastructure_payload() or {}
        topology = current.get("topology") or {}

        for device in topology.get("devices") or []:
            if not self._is_managed(device, service_id=service_id):
                continue

            device_id = str(device.get("device_id") or "").strip()

            if not device_id:
                continue

            self.observation_engine.process_result(
                ObserverResult(
                    success=False,
                    latency=0.0,
                    timestamp=observed_at,
                    message=("Etat Z-Wave inconnu car le controleur est indisponible."),
                    check=_NODE_CAPABILITY,
                    description="Etat vivant du noeud Z-Wave.",
                    metadata={
                        "target_type": "device",
                        "device_id": device_id,
                        "contributes_to_device_health": True,
                        "controller_service_id": service_id,
                        "status": "unknown",
                    },
                    health=HealthStatus.UNKNOWN,
                ),
                target_name=device_id,
                source=_NODE_CAPABILITY,
            )

    @staticmethod
    def _valid_nodes(value: object) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []

        nodes: list[dict[str, Any]] = []

        for candidate in value:
            if not isinstance(candidate, dict):
                continue

            node_id = candidate.get("node_id")

            if isinstance(node_id, bool):
                continue

            try:
                normalized_node_id = int(node_id)
            except (TypeError, ValueError):
                continue

            if normalized_node_id <= 0:
                continue

            node = dict(candidate)
            node["node_id"] = normalized_node_id
            nodes.append(node)

        return sorted(nodes, key=lambda node: int(node["node_id"]))

    @staticmethod
    def _gateway_device_id(
        payload: dict[str, Any],
        *,
        service_id: str,
    ) -> str | None:
        topology = payload.get("topology") or {}
        devices = topology.get("devices") or []
        services = payload.get("services") or []
        service_node_id = next(
            (
                service.get("node_id")
                for service in services
                if service.get("service_id") == service_id
            ),
            None,
        )
        node_matches = [
            device
            for device in devices
            if service_node_id is not None and device.get("node_id") == service_node_id
        ]

        if len(node_matches) == 1:
            return str(node_matches[0].get("device_id"))

        role_matches = [
            device
            for device in devices
            if (device.get("metadata") or {}).get("role") == "zwave_gateway"
        ]

        if len(role_matches) == 1:
            return str(role_matches[0].get("device_id"))

        return None

    @classmethod
    def _topology_device(
        cls,
        *,
        device_id: str,
        service_id: str,
        home_id: str | None,
        node: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = {
            "managed_by": _MANAGED_BY,
            "controller_service_id": service_id,
            "radio_kind": "zwave",
            "home_id": home_id,
            "zwave_node_id": node["node_id"],
            "location": cls._optional_text(node.get("location")),
            "manufacturer": cls._optional_text(node.get("manufacturer")),
            "product_id": node.get("product_id"),
            "product_type": node.get("product_type"),
            "firmware_version": cls._optional_text(node.get("firmware_version")),
            "can_sleep": bool(node.get("can_sleep", False)),
        }

        return {
            "device_id": device_id,
            "label": cls._node_label(node),
            "kind": "zwave_module",
            "node_id": None,
            "address": None,
            "metadata": {
                key: value for key, value in metadata.items() if value is not None
            },
        }

    @staticmethod
    def _node_label(node: dict[str, Any]) -> str:
        for key in ("name", "label"):
            value = node.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

        return f"Z-Wave {node['node_id']}"

    @staticmethod
    def _health(status: str) -> HealthStatus:
        if status in {"alive", "awake", "asleep"}:
            return HealthStatus.HEALTHY

        if status == "dead":
            return HealthStatus.UNHEALTHY

        return HealthStatus.UNKNOWN

    @staticmethod
    def _state_message(label: str, status: str) -> str:
        if status == "asleep":
            return f"{label} est endormi et vivant."

        if status in {"alive", "awake"}:
            return f"{label} est vivant."

        if status == "dead":
            return f"{label} ne repond plus au reseau Z-Wave."

        return f"L'etat vivant de {label} est inconnu."

    @staticmethod
    def _device_id(service_id: str, node_id: int) -> str:
        service_slug = re.sub(r"[^a-z0-9]+", "-", service_id.lower()).strip("-")
        return f"zwave-{service_slug or 'controller'}-node-{node_id}"

    @staticmethod
    def _is_managed(item: dict[str, Any], *, service_id: str) -> bool:
        metadata = item.get("metadata") or {}
        return (
            metadata.get("managed_by") == _MANAGED_BY
            and metadata.get("controller_service_id") == service_id
        )

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if value is None:
            return None

        text = str(value).strip()
        return text or None
