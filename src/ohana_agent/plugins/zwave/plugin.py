"""Z-Wave capability plugin."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any

from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_context import PluginContext
from ohana_agent.plugins.runtime.plugin_manifest import PluginManifest
from ohana_agent.plugins.runtime.plugin_runtime import PluginState
from ohana_agent.plugins.zwave.check import ZWaveCheck
from ohana_agent.plugins.zwave.config import ZWaveConfig
from ohana_agent.plugins.zwave.result import ZWaveNodeResult

if TYPE_CHECKING:
    from ohana_agent.observation.observer_result import ObserverResult


class ZWavePlugin(Plugin):
    """Plugin responsible for Z-Wave JS Server driver health checks."""

    def __init__(
        self,
        *,
        check: ZWaveCheck | None = None,
        config: ZWaveConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._state = PluginState.LOADED
        self._clock = clock or (lambda: datetime.now(UTC))
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
        from ohana_agent.observation.observer_result import ObserverResult

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
        now = self._clock()
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
                **self._silence(node, now),
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

    def _silence(self, node: ZWaveNodeResult, now: datetime) -> dict[str, Any]:
        """Measure how long a node has been silent against the configured delay.

        ``silent`` stays None when the node is not monitored or has no usable
        last contact: an unknown date is not evidence of silence.
        """
        threshold = self.config.silence_threshold_minutes(can_sleep=node.can_sleep)
        age_seconds: int | None = None

        if node.last_seen is not None:
            try:
                last_seen = datetime.fromisoformat(node.last_seen)
            except ValueError:
                last_seen = None

            if last_seen is not None:
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=UTC)

                age_seconds = max(0, int((now - last_seen).total_seconds()))

        return {
            "last_seen_age_seconds": age_seconds,
            "silence_threshold_minutes": threshold,
            "silent": (
                None
                if threshold is None or age_seconds is None
                else age_seconds > threshold * 60
            ),
        }

    def reconfigure(self, config: ZWaveConfig) -> None:
        """Replace Z-Wave services and policy without recreating the plugin."""
        self.config = config
