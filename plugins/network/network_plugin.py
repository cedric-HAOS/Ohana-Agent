"""Network equipment presence plugin."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from infrastructure.enums import HealthStatus
from plugin.plugin import Plugin
from plugin.plugin_context import PluginContext
from plugin.plugin_manifest import PluginManifest
from plugin.plugin_runtime import PluginState
from plugins.network.network_check import NetworkCheck
from plugins.network.network_config import NetworkConfig

if TYPE_CHECKING:
    from observer.observer_result import ObserverResult


class NetworkPlugin(Plugin):
    """Plugin responsible for lightweight topology device presence checks."""

    def __init__(
        self,
        *,
        check: NetworkCheck | None = None,
        config: NetworkConfig | None = None,
    ) -> None:
        self._state = PluginState.LOADED
        self._check = check or NetworkCheck()
        self.config = config or NetworkConfig()
        self._consecutive_failures: dict[str, int] = {}

    @property
    def name(self) -> str:
        return "network"

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def manifest(self) -> PluginManifest:
        """Return the network plugin manifest."""
        return PluginManifest(
            name="network",
            version="0.1.0",
            description="Network equipment presence plugin for Ohana-Agent.",
        )

    def register(self, context: PluginContext) -> None:
        """Register the network plugin in the Ohana-Agent context."""
        del context
        self._state = PluginState.REGISTERED

    def execute(self, **kwargs: Any) -> ObserverResult:
        """Probe one device through the common plugin API."""
        from observer.observer_result import ObserverResult

        address = kwargs.get("address")
        device_id = kwargs.get("device_id")
        label = kwargs.get("label", device_id)
        node_id = kwargs.get("node_id")

        if not isinstance(address, str) or not address.strip():
            raise ValueError(
                "NetworkPlugin.execute() requires a non-empty 'address' argument."
            )

        if not isinstance(device_id, str) or not device_id.strip():
            raise ValueError(
                "NetworkPlugin.execute() requires a non-empty 'device_id' argument."
            )

        if node_id is not None and (
            not isinstance(node_id, str) or not node_id.strip()
        ):
            raise ValueError(
                "NetworkPlugin.execute() requires 'node_id' to be null or non-empty."
            )

        resolved_device_id = device_id.strip()
        result = self._check.check(
            address.strip(),
            timeout=self.config.timeout,
            retries=self.config.retries,
        )
        health, success, message = self._evaluate(
            resolved_device_id,
            label=str(label or resolved_device_id),
            reachable=result.reachable,
            error=result.error,
        )

        return ObserverResult(
            success=success,
            latency=result.latency_ms or 0.0,
            health=health,
            message=message,
            check="network.reachable",
            description="Detect whether a declared topology device is present.",
            metadata={
                "target_type": "device",
                "device_id": resolved_device_id,
                "device_label": str(label or resolved_device_id),
                "node_id": node_id.strip() if isinstance(node_id, str) else None,
                "address": result.address,
                "resolved_address": result.resolved_address,
                "method": result.method,
                "attempts": result.attempts,
                "consecutive_failures": self._consecutive_failures.get(
                    resolved_device_id,
                    0,
                ),
                "failure_threshold": self.config.failure_threshold,
                "error": result.error,
            },
        )

    def test(self, **kwargs: Any) -> ObserverResult:
        """Execute an immediate check without changing failure history."""
        previous_failures = self._consecutive_failures.copy()

        try:
            return self.execute(**kwargs)
        finally:
            self._consecutive_failures = previous_failures

    def reconfigure(self, config: NetworkConfig) -> None:
        """Replace devices and policy without recreating the plugin."""
        self.config = config
        configured_ids = {device.name for device in config.devices}
        self._consecutive_failures = {
            device_id: failures
            for device_id, failures in self._consecutive_failures.items()
            if device_id in configured_ids
        }

    def _evaluate(
        self,
        device_id: str,
        *,
        label: str,
        reachable: bool | None,
        error: str | None,
    ) -> tuple[HealthStatus, bool, str]:
        if reachable is True:
            self._consecutive_failures.pop(device_id, None)
            return HealthStatus.HEALTHY, True, f"{label} is present on the network."

        if reachable is None:
            return (
                HealthStatus.UNKNOWN,
                False,
                error or f"Network presence of {label} could not be determined.",
            )

        failures = self._consecutive_failures.get(device_id, 0) + 1
        self._consecutive_failures[device_id] = failures

        if failures < self.config.failure_threshold:
            return (
                HealthStatus.UNKNOWN,
                False,
                f"{label} did not respond "
                f"({failures}/{self.config.failure_threshold} failed checks).",
            )

        return (
            HealthStatus.UNHEALTHY,
            False,
            f"{label} is absent after {failures} consecutive failed checks.",
        )
