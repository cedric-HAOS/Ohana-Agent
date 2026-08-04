"""Z-Wave capability plugin."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

from plugin.plugin import Plugin
from plugin.plugin_context import PluginContext
from plugin.plugin_manifest import PluginManifest
from plugin.plugin_runtime import PluginState
from plugins.zwave.zwave_check import ZWaveCheck
from plugins.zwave.zwave_config import ZWaveConfig

if TYPE_CHECKING:
    from observer.observer_result import ObserverResult


class ZWavePlugin(Plugin):
    """Plugin responsible for Z-Wave JS Server driver health checks."""

    def __init__(
        self,
        *,
        check: ZWaveCheck | None = None,
        config: ZWaveConfig | None = None,
    ) -> None:
        self._state = PluginState.LOADED
        self._check = check or ZWaveCheck()
        self.config = config or ZWaveConfig()

    @property
    def name(self) -> str:
        return "zwave"

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def manifest(self) -> PluginManifest:
        """Return the Z-Wave plugin manifest."""
        return PluginManifest(
            name="zwave",
            version="0.2.0",
            description="Z-Wave JS Server controller health plugin for Ohana-Agent.",
        )

    def register(self, context: PluginContext) -> None:
        """Register the Z-Wave plugin in the Ohana-Agent context."""
        del context
        self._state = PluginState.REGISTERED

    def execute(self, **kwargs: Any) -> ObserverResult:
        """Query one Z-Wave JS endpoint through the common plugin API."""
        from observer.observer_result import ObserverResult

        url = kwargs.get("url")

        if not isinstance(url, str) or not url.strip():
            raise ValueError(
                "ZWavePlugin.execute() requires a non-empty 'url' argument."
            )

        started_at = perf_counter()
        result = self._check.check(
            url.strip(),
            timeout=self.config.timeout,
            retries=self.config.retries,
            verify_tls=self.config.verify_tls,
        )
        elapsed_ms = (perf_counter() - started_at) * 1000
        message = (
            f"Z-Wave JS driver is ready through {result.url}."
            if result.healthy
            else result.error or f"Z-Wave controller is unavailable at {result.url}."
        )
        nodes = [
            {
                "node_id": node.node_id,
                "status": node.status,
                "alive": node.alive,
                "ready": node.ready,
                "name": node.name,
                "label": node.label,
                "location": node.location,
                "manufacturer": node.manufacturer,
                "product_id": node.product_id,
                "product_type": node.product_type,
                "firmware_version": node.firmware_version,
                "can_sleep": node.can_sleep,
                "last_seen": node.last_seen,
            }
            for node in result.nodes
        ]

        return ObserverResult(
            success=result.healthy,
            latency=elapsed_ms,
            message=message,
            check="zwave.status",
            description="Check the Z-Wave JS Server driver through WebSocket.",
            metadata={
                "url": result.url,
                "status_code": result.status_code,
                "response": result.response,
                "server_version": result.server_version,
                "driver_version": result.driver_version,
                "home_id": result.home_id,
                "node_count": result.node_count,
                "nodes": nodes,
                "discovery_complete": result.discovery_complete,
                "attempts": result.attempts,
                "verify_tls": self.config.verify_tls,
                "error": result.error,
            },
        )

    def reconfigure(self, config: ZWaveConfig) -> None:
        """Replace Z-Wave services and policy without recreating the plugin."""
        self.config = config
