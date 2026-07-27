"""DHCP capability plugin."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

from plugin.plugin import Plugin
from plugin.plugin_context import PluginContext
from plugin.plugin_manifest import PluginManifest
from plugin.plugin_runtime import PluginState
from plugins.dhcp.dhcp_check import DHCPCheck
from plugins.dhcp.dhcp_check_result import DHCPCheckResult
from plugins.dhcp.dhcp_config import DHCPConfig

if TYPE_CHECKING:
    from observer.observer_result import ObserverResult


class DHCPPlugin(Plugin):
    """Plugin responsible for observing the local DHCP capability."""

    def __init__(
        self,
        *,
        check: DHCPCheck | None = None,
        config: DHCPConfig | None = None,
    ) -> None:
        self._state = PluginState.LOADED
        self._check = check or DHCPCheck()
        self.config = config or DHCPConfig()

    @property
    def name(self) -> str:
        return "dhcp"

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def manifest(self) -> PluginManifest:
        """Return the DHCP plugin manifest."""
        return PluginManifest(
            name="dhcp",
            version="0.1.0",
            description="Local dnsmasq DHCP capability plugin for Ohana-Agent.",
        )

    def register(self, context: PluginContext) -> None:
        """Register the DHCP plugin in the Ohana-Agent context."""
        del context
        self._state = PluginState.REGISTERED

    def execute(self, **kwargs: Any) -> ObserverResult:
        """Observe one configured DHCP service through the common plugin API."""
        from observer.observer_result import ObserverResult

        server = kwargs.get("server")
        service_id = kwargs.get("service_id")

        if not isinstance(server, str) or not server.strip():
            raise ValueError(
                "DHCPPlugin.execute() requires a non-empty 'server' argument."
            )

        if not isinstance(service_id, str) or not service_id.strip():
            raise ValueError(
                "DHCPPlugin.execute() requires a non-empty 'service_id' argument."
            )

        port = kwargs.get("port", 67)

        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65_535
        ):
            raise ValueError(
                "DHCPPlugin.execute() requires 'port' to be between 1 and 65535."
            )

        started_at = perf_counter()
        result = self.check(
            server.strip(),
            port=port,
            service_id=service_id.strip(),
        )
        elapsed_ms = (perf_counter() - started_at) * 1000
        success, message = self._evaluate(result)

        return ObserverResult(
            success=success,
            latency=elapsed_ms,
            message=message,
            check="dhcp.status",
            description=(
                "Observe the local dnsmasq service, lease pool and active leases."
            ),
            metadata={
                "server": result.server,
                "port": result.port,
                "service_id": result.service_id,
                "service_active": result.service_active,
                "range_start": result.range_start,
                "range_end": result.range_end,
                "pool_size": result.pool_size,
                "lease_count": result.lease_count,
                "available_address_count": result.available_address_count,
                "expired_lease_count": result.expired_lease_count,
                "pool_usage_percent": result.pool_usage_percent,
                "status_output": result.status_output,
                "error": result.error,
            },
        )

    def check(
        self,
        server: str,
        *,
        port: int,
        service_id: str,
    ) -> DHCPCheckResult:
        """Execute one configured DHCP capability check."""
        return self._check.check(
            server,
            port=port,
            service_id=service_id,
            main_config_path=self.config.main_config_path,
            leases_path=self.config.leases_path,
            service_status_command=self.config.service_status_command,
            timeout=self.config.timeout,
        )

    def reconfigure(self, config: DHCPConfig) -> None:
        """Replace DHCP services and local state paths without recreating plugin."""
        self.config = config

    def _evaluate(self, result: DHCPCheckResult) -> tuple[bool, str]:
        if not result.healthy:
            return False, result.error or "DHCP status observation failed."

        if result.pool_usage_percent is None:
            return False, "DHCP pool usage could not be calculated."

        threshold = self.config.policy.maximum_pool_usage_percent

        if result.pool_usage_percent >= threshold:
            return (
                False,
                "DHCP pool usage exceeds the configured threshold for "
                f"{result.service_id}: {result.pool_usage_percent:.1f}%.",
            )

        return (
            True,
            f"DHCP service {result.service_id} is available with "
            f"{result.lease_count} active lease(s) "
            f"({result.pool_usage_percent:.1f}% of the pool).",
        )
