"""MQTT capability plugin."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

from plugin.plugin import Plugin
from plugin.plugin_context import PluginContext
from plugin.plugin_manifest import PluginManifest
from plugin.plugin_runtime import PluginState
from plugins.mqtt.home_assistant_publisher import MQTTHomeAssistantPublisher
from plugins.mqtt.mqtt_check import MQTTCheck
from plugins.mqtt.mqtt_check_result import MQTTCheckResult
from plugins.mqtt.mqtt_config import MQTTConfig

if TYPE_CHECKING:
    from configuration.infrastructure import InfrastructureConfig
    from observer.observer_result import ObserverResult


class MQTTPlugin(Plugin):
    """Plugin responsible for MQTT round-trip capability checks."""

    def __init__(
        self,
        *,
        check: MQTTCheck | None = None,
        config: MQTTConfig | None = None,
        home_assistant_publisher: MQTTHomeAssistantPublisher | None = None,
    ) -> None:
        self._state = PluginState.LOADED
        self._check = check or MQTTCheck()
        self.config = config or MQTTConfig()
        self.home_assistant_publisher = home_assistant_publisher

    @property
    def name(self) -> str:
        return "mqtt"

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def manifest(self) -> PluginManifest:
        """Return the MQTT plugin manifest."""
        return PluginManifest(
            name="mqtt",
            version="0.1.0",
            description="MQTT capability plugin for Ohana-Agent.",
        )

    def register(self, context: PluginContext) -> None:
        """Register the MQTT plugin in the Ohana-Agent context."""
        del context
        self._state = PluginState.REGISTERED

    def execute(self, **kwargs: Any) -> ObserverResult:
        """Execute an MQTT round trip through the common plugin API."""
        from observer.observer_result import ObserverResult

        broker = kwargs.get("broker")

        if not isinstance(broker, str) or not broker.strip():
            raise ValueError(
                "MQTTPlugin.execute() requires a non-empty 'broker' argument."
            )

        port = kwargs.get("port", 1883)

        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65_535
        ):
            raise ValueError(
                "MQTTPlugin.execute() requires 'port' to be between 1 and 65535."
            )

        service_id = kwargs.get("service_id", "mqtt")

        if not isinstance(service_id, str) or not service_id.strip():
            raise ValueError(
                "MQTTPlugin.execute() requires 'service_id' to be a non-empty string."
            )

        started_at = perf_counter()
        result = self.check(
            broker.strip(),
            port=port,
            service_id=service_id.strip(),
        )
        elapsed_ms = (perf_counter() - started_at) * 1000

        return ObserverResult(
            success=result.healthy,
            latency=(
                result.round_trip_ms if result.round_trip_ms is not None else elapsed_ms
            ),
            message=self._message(result),
            check="mqtt.roundtrip",
            description=(
                "Connect, subscribe, publish and receive through an MQTT broker."
            ),
            metadata={
                "broker": result.broker,
                "port": result.port,
                "topic": result.topic,
                "qos": result.qos,
                "client_id": result.client_id,
                "connected": result.connected,
                "subscribed": result.subscribed,
                "published": result.published,
                "received": result.received,
                "round_trip_ms": result.round_trip_ms,
                "tls_enabled": result.tls_enabled,
                "attempts": result.attempts,
                "error": result.error,
            },
        )

    def check(
        self,
        broker: str,
        *,
        port: int = 1883,
        service_id: str = "mqtt",
    ) -> MQTTCheckResult:
        """Execute one configured MQTT capability check."""
        return self._check.check(
            broker,
            port=port,
            timeout=self.config.timeout,
            retries=self.config.retries,
            keepalive_seconds=self.config.keepalive_seconds,
            service_id=service_id,
            client_id_prefix=self.config.client_id_prefix,
            topic_prefix=self.config.topic_prefix,
            qos=self.config.qos,
            username=self.config.authentication.username,
            password=self.config.authentication.password,
            tls_enabled=self.config.tls.enabled,
            ca_file=self.config.tls.ca_file,
            tls_insecure=self.config.tls.insecure,
        )

    def reconfigure(
        self,
        config: MQTTConfig,
        *,
        infrastructure: InfrastructureConfig | None = None,
    ) -> None:
        """Replace MQTT brokers and settings without recreating the plugin."""
        self.config = config

        if self.home_assistant_publisher is not None:
            self.home_assistant_publisher.reconfigure(
                config,
                infrastructure=infrastructure,
            )

    @staticmethod
    def _message(result: MQTTCheckResult) -> str:
        if result.healthy:
            latency = (
                f" in {result.round_trip_ms:.3f} ms"
                if result.round_trip_ms is not None
                else ""
            )
            return f"MQTT round trip succeeded for {result.broker}{latency}."

        return result.error or f"MQTT round trip failed for {result.broker}."
