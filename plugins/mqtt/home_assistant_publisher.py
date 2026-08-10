"""Publish the Ohana health summary through MQTT Discovery."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from threading import Event, RLock
from time import monotonic
from typing import Any

from configuration.infrastructure import InfrastructureConfig
from observer.observation import Observation
from observer.observation_exporter import ObservationExporter
from observer.observation_status import ObservationStatus
from plugins.mqtt.host_health import HostHealthSnapshot
from plugins.mqtt.mqtt_config import MQTTConfig

LOGGER = logging.getLogger(__name__)

_STATUS_PRIORITY = {
    "healthy": 0,
    "unknown": 1,
    "degraded": 2,
    "unhealthy": 3,
}


@dataclass(frozen=True, slots=True)
class MQTTHomeAssistantAlert:
    """Stable Home Assistant description of one active anomaly."""

    equipment: str
    node: str
    service: str
    service_name: str
    capability: str
    status: str


@dataclass(frozen=True, slots=True)
class MQTTHomeAssistantHealthSummary:
    """Compact infrastructure summary published to Home Assistant."""

    score: float | None
    state: str
    active_alerts: int
    critical_incidents: int
    healthy_services: int
    degraded_services: int
    unavailable_services: int
    stale_capabilities: int
    updated_at: str
    critical_service: str | None = None
    critical_equipment: str | None = None
    critical_capability: str | None = None
    critical_message: str | None = None
    affected_equipment: tuple[str, ...] = ()
    affected_capabilities: tuple[str, ...] = ()
    alerts: tuple[MQTTHomeAssistantAlert, ...] = ()

    def to_json(self) -> str:
        """Serialize the summary using stable compact JSON."""
        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            separators=(",", ":"),
        )


class MQTTHomeAssistantPublisher(ObservationExporter):
    """Export observations as one Home Assistant health device."""

    def __init__(
        self,
        *,
        config: MQTTConfig,
        infrastructure: InfrastructureConfig,
        client_factory: Callable[[str], Any] | None = None,
        utc_now: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
        agent_version: str | None = None,
    ) -> None:
        self.config = config
        self.infrastructure = infrastructure
        self._client_factory = client_factory or self._create_paho_client
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._monotonic_clock = monotonic_clock
        self._agent_version = agent_version or self._resolve_agent_version()
        self._latest_host_health: HostHealthSnapshot | None = None
        self._client: Any | None = None
        self._connected = False
        self._started = False
        self._connected_event = Event()
        self._lock = RLock()
        self._latest_observations: dict[tuple[str, str, str], Observation] = {}
        self._last_summary_state: tuple[Any, ...] | None = None
        self._next_heartbeat_at: float | None = None

    @property
    def enabled(self) -> bool:
        """Return whether Home Assistant export can be started."""
        return self.config.home_assistant.enabled and any(
            broker.enabled for broker in self.config.brokers
        )

    @property
    def connected(self) -> bool:
        """Return whether the publisher is connected to its broker."""
        return self._connected

    def start(self) -> None:
        """Connect to the primary MQTT broker and publish discovery."""
        with self._lock:
            if self._started or not self.enabled:
                return

            broker = next(broker for broker in self.config.brokers if broker.enabled)
            settings = self.config.home_assistant
            client_id = f"{self.config.client_id_prefix}-home-assistant"

            try:
                client = self._client_factory(client_id)
                client.on_connect = self._on_connect
                client.on_disconnect = self._on_disconnect

                if self.config.authentication.username is not None:
                    client.username_pw_set(
                        self.config.authentication.username,
                        self.config.authentication.password,
                    )

                if self.config.tls.enabled:
                    client.tls_set(ca_certs=self.config.tls.ca_file)
                    client.tls_insecure_set(self.config.tls.insecure)

                client.will_set(
                    self._status_topic(),
                    payload="offline",
                    qos=self.config.qos,
                    retain=True,
                )

                self._client = client
                self._connected_event.clear()
                result = client.connect(
                    broker.address,
                    broker.port,
                    keepalive=self.config.keepalive_seconds,
                )
                if not self._successful_code(result):
                    raise RuntimeError(
                        f"MQTT connect request failed with code {result}."
                    )

                client.loop_start()
                self._started = True

                if not self._connected_event.wait(self.config.timeout):
                    raise TimeoutError(
                        "Timed out while connecting the Home Assistant MQTT export."
                    )

                if not self._connected:
                    raise RuntimeError(
                        "The Home Assistant MQTT export connection was rejected."
                    )

                self._next_heartbeat_at = (
                    self._monotonic_clock() + settings.heartbeat_seconds
                )
            except Exception as error:
                LOGGER.warning(
                    "Unable to start Home Assistant MQTT export: %s",
                    error,
                )
                self._cleanup_client()

    def stop(self) -> None:
        """Publish the offline state and close the MQTT connection."""
        with self._lock:
            client = self._client

            if client is None:
                self._started = False
                self._connected = False
                self._next_heartbeat_at = None
                return

            if self._connected:
                self._safe_publish(
                    self._status_topic(),
                    "offline",
                    retain=True,
                )

            try:
                client.disconnect()
            except Exception:
                LOGGER.debug("Unable to disconnect Home Assistant MQTT client.")

            try:
                client.loop_stop()
            except Exception:
                LOGGER.debug("Unable to stop Home Assistant MQTT client loop.")

            self._client = None
            self._started = False
            self._connected = False
            self._connected_event.clear()
            self._next_heartbeat_at = None

    def tick(self) -> None:
        """Publish the periodic health heartbeat when it becomes due."""
        with self._lock:
            if not self.enabled:
                return

            if not self._started:
                self.start()

            if not self._connected:
                return

            now = self._monotonic_clock()
            if self._next_heartbeat_at is None or now < self._next_heartbeat_at:
                return

            self._publish_summary(force=False)
            self._next_heartbeat_at = now + self.config.home_assistant.heartbeat_seconds

    def export(self, observation: Observation) -> None:
        """Store one observation and publish the summary when it changes."""
        with self._lock:
            key = (
                observation.node,
                observation.service,
                observation.capability,
            )
            current = self._latest_observations.get(key)

            if current is None or observation.timestamp >= current.timestamp:
                self._latest_observations[key] = observation

            if not self.enabled:
                return

            if not self._started:
                self.start()

            if self._connected:
                self._publish_summary(force=False)

    def reconfigure(
        self,
        config: MQTTConfig,
        *,
        infrastructure: InfrastructureConfig | None = None,
    ) -> None:
        """Apply broker and Home Assistant export settings immediately."""
        with self._lock:
            if config == self.config:
                if infrastructure is not None:
                    self.infrastructure = infrastructure
                    self._last_summary_state = None

                if self.enabled and not self._started:
                    self.start()
                elif infrastructure is not None and self._connected:
                    self._publish_summary(force=True)

                return

            self.stop()
            self.config = config
            if infrastructure is not None:
                self.infrastructure = infrastructure
            self._last_summary_state = None
            if self.enabled:
                self.start()

    def update_infrastructure(self, infrastructure: InfrastructureConfig) -> None:
        """Replace the topology and service policies used by the summary."""
        with self._lock:
            self.infrastructure = infrastructure
            self._last_summary_state = None
            if self._connected:
                self._publish_summary(force=True)

    def build_summary(self) -> MQTTHomeAssistantHealthSummary:
        """Build the current health summary from the latest observations."""
        now = self._utc_now()
        observations = tuple(self._latest_observations.values())
        service_statuses = self._service_statuses(observations)
        logical_service_statuses = self._logical_service_statuses(service_statuses)
        device_statuses = self._device_statuses(
            observations,
            service_statuses,
            logical_service_statuses,
        )

        known_device_statuses = tuple(
            status for status in device_statuses.values() if status != "unknown"
        )
        healthy_devices = sum(status == "healthy" for status in known_device_statuses)
        score = (
            round(healthy_devices / len(known_device_statuses) * 100, 1)
            if known_device_statuses
            else None
        )

        if any(status == "unhealthy" for status in known_device_statuses):
            state = "critical"
        elif any(status == "degraded" for status in known_device_statuses):
            state = "degraded"
        elif healthy_devices > 0:
            state = "healthy"
        else:
            state = "unavailable"

        active_alerts = sum(
            self._normalize_status(observation.status) in {"degraded", "unhealthy"}
            for observation in observations
        )
        stale_capabilities = sum(
            self._is_stale(observation, now=now) for observation in observations
        )

        healthy_services = sum(
            status == "healthy" for status in logical_service_statuses.values()
        )
        degraded_services = sum(
            status == "degraded" for status in logical_service_statuses.values()
        )
        unavailable_services = sum(
            status == "unhealthy" for status in logical_service_statuses.values()
        )

        critical_logical_services = {
            self._logical_service_key(service)
            for service in self.infrastructure.services
            if service.enabled and service.critical
        }
        critical_incidents = sum(
            logical_service_statuses.get(key) == "unhealthy"
            for key in critical_logical_services
        )
        critical_service_instances = {
            (service.node, service.id): service
            for service in self.infrastructure.services
            if service.enabled
            and service.critical
            and logical_service_statuses.get(self._logical_service_key(service))
            == "unhealthy"
        }
        critical_observation = self._first_critical_observation(
            observations,
            critical_service_instances,
        )
        alerts = self._active_alert_details(observations)
        critical_equipment = None
        if critical_observation is not None:
            critical_equipment = self._device_label_for_node(critical_observation.node)

        return MQTTHomeAssistantHealthSummary(
            score=score,
            state=state,
            active_alerts=active_alerts,
            critical_incidents=critical_incidents,
            healthy_services=healthy_services,
            degraded_services=degraded_services,
            unavailable_services=unavailable_services,
            stale_capabilities=stale_capabilities,
            updated_at=now.isoformat(),
            critical_service=(
                critical_observation.service
                if critical_observation is not None
                else None
            ),
            critical_equipment=critical_equipment,
            critical_capability=(
                critical_observation.capability
                if critical_observation is not None
                else None
            ),
            critical_message=(
                critical_observation.message
                if critical_observation is not None
                else None
            ),
            affected_equipment=tuple(
                sorted({alert.equipment for alert in alerts}, key=str.casefold)
            ),
            affected_capabilities=tuple(
                sorted({alert.capability for alert in alerts}, key=str.casefold)
            ),
            alerts=alerts,
        )

    def _on_connect(
        self,
        client: Any,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        del client, userdata, flags, properties

        if not self._successful_code(reason_code):
            self._connected = False
            self._connected_event.set()
            LOGGER.warning(
                "Home Assistant MQTT export connection rejected: %s",
                reason_code,
            )
            return

        self._connected = True
        self._connected_event.set()
        self._publish_discovery()
        self._safe_publish(self._status_topic(), "online", retain=True)
        self._publish_summary(force=True)
        self._publish_latest_host_health()

    def _on_disconnect(
        self,
        client: Any,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        del client, userdata, disconnect_flags, reason_code, properties
        self._connected = False

    def _publish_discovery(self) -> None:
        if not self.config.home_assistant.discovery_enabled:
            return

        for component, object_id, payload in self._discovery_payloads():
            topic = (
                f"{self.config.home_assistant.discovery_prefix}/"
                f"{component}/{object_id}/config"
            )
            self._safe_publish(
                topic,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                retain=True,
            )

        for component, object_id in self._obsolete_discovery_entities():
            topic = (
                f"{self.config.home_assistant.discovery_prefix}/"
                f"{component}/{object_id}/config"
            )
            self._safe_publish(topic, "", retain=True)

    @staticmethod
    def _obsolete_discovery_entities() -> tuple[tuple[str, str], ...]:
        """Return entities that must be removed from Home Assistant."""
        return (("sensor", "ohana_last_evaluation"),)

    def _publish_summary(self, *, force: bool) -> None:
        summary = self.build_summary()
        payload = summary.to_json()
        state = self._summary_state(summary)

        if not force and state == self._last_summary_state:
            return

        if self._safe_publish(self._summary_topic(), payload, retain=True):
            self._last_summary_state = state

    def publish_host_health(self, snapshot: HostHealthSnapshot) -> None:
        """Publish the shared host snapshot when MQTT is connected."""
        with self._lock:
            self._latest_host_health = snapshot
            self._publish_latest_host_health()

    def _publish_latest_host_health(self) -> None:
        if not self._connected or self._latest_host_health is None:
            return
        self._safe_publish(
            self._host_health_topic(),
            self._latest_host_health.to_json(),
            retain=True,
        )

    @staticmethod
    def _summary_state(
        summary: MQTTHomeAssistantHealthSummary,
    ) -> tuple[Any, ...]:
        """Return the meaningful Home Assistant state."""
        return (
            summary.score,
            summary.state,
            summary.active_alerts,
            summary.critical_incidents,
            summary.healthy_services,
            summary.degraded_services,
            summary.unavailable_services,
            summary.stale_capabilities,
            summary.critical_service,
            summary.critical_equipment,
            summary.critical_capability,
            summary.affected_equipment,
            summary.affected_capabilities,
            summary.alerts,
        )

    def _safe_publish(self, topic: str, payload: str, *, retain: bool) -> bool:
        client = self._client
        if client is None:
            return False

        try:
            result = client.publish(
                topic,
                payload,
                qos=self.config.qos,
                retain=retain,
            )
            return self._successful_code(getattr(result, "rc", result))
        except Exception as error:
            LOGGER.warning(
                "Unable to publish MQTT topic %s: %s",
                topic,
                error,
            )
            return False

    def _discovery_payloads(self) -> tuple[tuple[str, str, dict[str, Any]], ...]:
        state_topic = self._summary_topic()
        availability_topic = self._status_topic()
        device = {
            "identifiers": ["ohana-platform"],
            "name": "Ohana Platform",
            "manufacturer": "Ohana",
            "model": "Ohana Platform",
            "sw_version": self._agent_version,
        }
        origin = {
            "name": "Ohana-Agent",
            "sw_version": self._agent_version,
        }
        common = {
            "state_topic": state_topic,
            "availability_topic": availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device,
            "origin": origin,
        }
        host_state_topic = self._host_health_topic()
        host_common = {
            "state_topic": host_state_topic,
            "availability_topic": availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": {
                "identifiers": ["ohana-host"],
                "name": "Ohana Host",
                "manufacturer": "Ohana",
                "model": "Agent Host",
                "sw_version": self._agent_version,
            },
            "origin": origin,
        }

        def sensor(
            object_id: str,
            name: str,
            field: str,
            **extra: Any,
        ) -> tuple[str, str, dict[str, Any]]:
            return (
                "sensor",
                object_id,
                {
                    **common,
                    "name": name,
                    "unique_id": object_id,
                    "object_id": object_id,
                    "value_template": f"{{{{ value_json.{field} }}}}",
                    **extra,
                },
            )

        def host_sensor(
            object_id: str,
            name: str,
            field: str,
            *,
            nullable: bool = False,
            **extra: Any,
        ) -> tuple[str, str, dict[str, Any]]:
            value_template = f"{{{{ value_json.{field} }}}}"
            if nullable:
                value_template = (
                    f"{{{{ value_json.{field} if value_json.{field} is not none "
                    f"else 'unknown' }}}}"
                )
            return (
                "sensor",
                object_id,
                {
                    **host_common,
                    "name": name,
                    "unique_id": object_id,
                    "object_id": object_id,
                    "value_template": value_template,
                    **extra,
                },
            )

        return (
            sensor(
                "ohana_health_score",
                "Score de santé global",
                "score",
                unit_of_measurement="%",
                state_class="measurement",
                icon="mdi:heart-pulse",
            ),
            sensor(
                "ohana_health_state",
                "État global",
                "state",
                icon="mdi:shield-heart",
                json_attributes_topic=state_topic,
                json_attributes_template=(
                    "{{ {"
                    "'critical_service': value_json.critical_service, "
                    "'critical_equipment': value_json.critical_equipment, "
                    "'critical_capability': value_json.critical_capability"
                    "} | tojson }}"
                ),
            ),
            (
                "binary_sensor",
                "ohana_critical_incident",
                {
                    **common,
                    "name": "Incident critique actif",
                    "unique_id": "ohana_critical_incident",
                    "object_id": "ohana_critical_incident",
                    "value_template": (
                        "{{ 'ON' if value_json.critical_incidents | int > 0 "
                        "else 'OFF' }}"
                    ),
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device_class": "problem",
                },
            ),
            sensor(
                "ohana_active_alerts",
                "Alertes actives",
                "active_alerts",
                state_class="measurement",
                icon="mdi:alert-circle-outline",
                json_attributes_topic=state_topic,
                json_attributes_template=(
                    "{{ {"
                    "'affected_equipment': value_json.affected_equipment, "
                    "'affected_capabilities': value_json.affected_capabilities, "
                    "'alerts': value_json.alerts"
                    "} | tojson }}"
                ),
            ),
            sensor(
                "ohana_degraded_services",
                "Services dégradés",
                "degraded_services",
                state_class="measurement",
                icon="mdi:alert-outline",
            ),
            sensor(
                "ohana_unavailable_services",
                "Services indisponibles",
                "unavailable_services",
                state_class="measurement",
                icon="mdi:server-off",
            ),
            sensor(
                "ohana_stale_capabilities",
                "Capacités sans observation récente",
                "stale_capabilities",
                state_class="measurement",
                icon="mdi:clock-alert-outline",
            ),
            host_sensor(
                "ohana_host_health_state",
                "État de santé",
                "state",
                icon="mdi:server-heart",
                json_attributes_topic=host_state_topic,
                json_attributes_template=(
                    "{{ {"
                    "'reasons': value_json.reasons, "
                    "'hostname': value_json.hostname, "
                    "'operating_system': value_json.operating_system, "
                    "'kernel': value_json.kernel, "
                    "'cpu_count': value_json.cpu_count, "
                    "'memory_available_bytes': value_json.memory_available_bytes, "
                    "'disk_free_bytes': value_json.disk_free_bytes, "
                    "'agent_restarts': value_json.agent_restarts, "
                    "'failed_systemd_units': value_json.failed_systemd_units"
                    "} | tojson }}"
                ),
            ),
            (
                "binary_sensor",
                "ohana_host_critical_incident",
                {
                    **host_common,
                    "name": "Incident critique",
                    "unique_id": "ohana_host_critical_incident",
                    "object_id": "ohana_host_critical_incident",
                    "value_template": (
                        "{{ 'ON' if value_json.state == 'critical' else 'OFF' }}"
                    ),
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device_class": "problem",
                },
            ),
            host_sensor(
                "ohana_host_cpu_usage",
                "Utilisation CPU",
                "cpu_percent",
                nullable=True,
                unit_of_measurement="%",
                state_class="measurement",
                icon="mdi:cpu-64-bit",
            ),
            host_sensor(
                "ohana_host_load",
                "Charge normalisée",
                "load_1m_per_cpu",
                nullable=True,
                state_class="measurement",
                icon="mdi:gauge",
            ),
            host_sensor(
                "ohana_host_memory_usage",
                "Utilisation mémoire",
                "memory_percent",
                nullable=True,
                unit_of_measurement="%",
                state_class="measurement",
                icon="mdi:memory",
            ),
            host_sensor(
                "ohana_host_swap_usage",
                "Utilisation swap",
                "swap_percent",
                nullable=True,
                unit_of_measurement="%",
                state_class="measurement",
                icon="mdi:swap-horizontal",
            ),
            host_sensor(
                "ohana_host_disk_usage",
                "Utilisation disque racine",
                "disk_percent",
                nullable=True,
                unit_of_measurement="%",
                state_class="measurement",
                icon="mdi:harddisk",
            ),
            host_sensor(
                "ohana_host_temperature",
                "Température CPU",
                "temperature_c",
                nullable=True,
                unit_of_measurement="°C",
                device_class="temperature",
                state_class="measurement",
            ),
            host_sensor(
                "ohana_host_uptime",
                "Uptime hôte",
                "host_uptime",
                icon="mdi:timer-outline",
            ),
            host_sensor(
                "ohana_agent_uptime",
                "Uptime Agent",
                "agent_uptime",
                icon="mdi:timer-cog-outline",
            ),
        )

    def _service_statuses(
        self,
        observations: tuple[Observation, ...],
    ) -> dict[tuple[str, str], str]:
        grouped: dict[tuple[str, str], list[str]] = {}
        services = {
            (service.node, service.id)
            for service in self.infrastructure.services
            if service.enabled
        }

        for observation in observations:
            key = (observation.node, observation.service)
            if key not in services:
                continue
            grouped.setdefault(key, []).append(
                self._normalize_status(observation.status)
            )

        return {key: self._most_severe(statuses) for key, statuses in grouped.items()}

    def _logical_service_statuses(
        self,
        service_statuses: dict[tuple[str, str], str],
    ) -> dict[tuple[str, ...], str]:
        """Aggregate redundant instances into Home Assistant logical services."""
        grouped: dict[tuple[str, ...], list[str]] = {}

        for service in self.infrastructure.services:
            if not service.enabled:
                continue

            status = service_statuses.get((service.node, service.id))
            if status is None:
                continue

            key = self._logical_service_key(service)
            grouped.setdefault(key, []).append(status)

        return {
            key: (
                self._redundant_service_status(statuses)
                if key[0] == "availability_group"
                else self._most_severe(statuses)
            )
            for key, statuses in grouped.items()
        }

    def _device_statuses(
        self,
        observations: tuple[Observation, ...],
        service_statuses: dict[tuple[str, str], str],
        logical_service_statuses: dict[tuple[str, ...], str],
    ) -> dict[str, str]:
        del observations
        topology = self.infrastructure.topology
        if topology is None:
            return {}

        services_by_node: dict[str, list[str]] = {}

        for service in self.infrastructure.services:
            if not service.enabled:
                continue

            status = service_statuses.get((service.node, service.id))
            if status is None:
                continue

            impact = self._service_parent_impact(
                status,
                critical=service.critical,
                logical_status=logical_service_statuses.get(
                    self._logical_service_key(service),
                    status,
                ),
            )
            services_by_node.setdefault(service.node, []).append(impact)

        return {
            device.id: self._most_severe(services_by_node.get(device.node or "", []))
            for device in topology.devices
            if device.node is not None
        }

    def _first_critical_observation(
        self,
        observations: tuple[Observation, ...],
        critical_services: dict[tuple[str, str], Any],
    ) -> Observation | None:
        candidates = [
            observation
            for observation in observations
            if (observation.node, observation.service) in critical_services
            and self._normalize_status(observation.status) == "unhealthy"
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda observation: observation.timestamp)

    def _active_alert_details(
        self,
        observations: tuple[Observation, ...],
    ) -> tuple[MQTTHomeAssistantAlert, ...]:
        """Describe every active degraded or unhealthy capability."""
        services = {
            (service.node, service.id): service
            for service in self.infrastructure.services
        }
        alerts: list[MQTTHomeAssistantAlert] = []

        for observation in observations:
            status = self._normalize_status(observation.status)
            if status not in {"degraded", "unhealthy"}:
                continue

            service = services.get((observation.node, observation.service))
            alerts.append(
                MQTTHomeAssistantAlert(
                    equipment=(
                        self._device_label_for_node(observation.node)
                        or observation.node
                    ),
                    node=observation.node,
                    service=observation.service,
                    service_name=(
                        service.name if service is not None else observation.service
                    ),
                    capability=observation.capability,
                    status=status,
                )
            )

        return tuple(
            sorted(
                alerts,
                key=lambda alert: (
                    -_STATUS_PRIORITY[alert.status],
                    alert.equipment.casefold(),
                    alert.service.casefold(),
                    alert.capability.casefold(),
                ),
            )
        )

    def _device_label_for_node(self, node_id: str) -> str | None:
        topology = self.infrastructure.topology
        if topology is None:
            return node_id

        for device in topology.devices:
            if device.node == node_id:
                return device.label

        return node_id

    def _is_stale(self, observation: Observation, *, now: datetime) -> bool:
        stale_after = max(
            self.config.home_assistant.heartbeat_seconds * 3,
            180,
        )
        timestamp = observation.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return (now - timestamp).total_seconds() > stale_after

    @staticmethod
    def _normalize_status(status: ObservationStatus | str) -> str:
        normalized = str(status).lower()
        if normalized in {"unhealthy", "unavailable"}:
            return "unhealthy"
        if normalized in {"degraded", "stale"}:
            return "degraded"
        if normalized == "healthy":
            return "healthy"
        return "unknown"

    def _logical_service_key(self, service: Any) -> tuple[str, ...]:
        availability_group = service.metadata.get("availability_group")
        if isinstance(availability_group, str) and availability_group.strip():
            return ("availability_group", availability_group.strip())

        # Existing installations predate availability_group. Two enabled DNS
        # instances are redundant by default so an upgrade immediately keeps
        # DNS available when only one resolver fails.
        if (
            service.type == "dns"
            and sum(
                candidate.enabled and candidate.type == "dns"
                for candidate in self.infrastructure.services
            )
            > 1
        ):
            return ("availability_group", "dns")

        return ("service", service.node, service.id)

    @staticmethod
    def _service_parent_impact(
        status: str,
        *,
        critical: bool,
        logical_status: str,
    ) -> str:
        if status == "unhealthy":
            if logical_status == "degraded":
                return "degraded"
            return "unhealthy" if critical else "degraded"
        if status == "degraded":
            return "degraded"
        if status == "unknown":
            return "degraded" if critical else "unknown"
        return "healthy"

    @staticmethod
    def _most_severe(statuses: tuple[str, ...] | list[str]) -> str:
        return max(
            statuses,
            key=lambda status: _STATUS_PRIORITY.get(status, 1),
            default="unknown",
        )

    @staticmethod
    def _redundant_service_status(statuses: list[str]) -> str:
        """Return the availability of an at-least-one redundant service."""
        unique_statuses = set(statuses)
        if len(unique_statuses) == 1:
            return statuses[0]
        return "degraded"

    def _summary_topic(self) -> str:
        return f"{self.config.home_assistant.topic_prefix}/health/summary"

    def _status_topic(self) -> str:
        return f"{self.config.home_assistant.topic_prefix}/status"

    def _host_health_topic(self) -> str:
        return f"{self.config.home_assistant.topic_prefix}/host/health"

    def _cleanup_client(self) -> None:
        client = self._client
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
            try:
                client.loop_stop()
            except Exception:
                pass
        self._client = None
        self._started = False
        self._connected = False
        self._connected_event.clear()
        self._next_heartbeat_at = None

    @staticmethod
    def _create_paho_client(client_id: str) -> Any:
        try:
            from paho.mqtt import client as mqtt
        except ImportError as error:
            raise RuntimeError(
                "The paho-mqtt dependency is required by the MQTT plugin."
            ) from error

        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )

    @staticmethod
    def _resolve_agent_version() -> str:
        try:
            return package_version("ohana-agent")
        except PackageNotFoundError:
            return "unknown"

    @staticmethod
    def _successful_code(code: Any) -> bool:
        try:
            return int(code) == 0
        except (TypeError, ValueError):
            return code == 0
