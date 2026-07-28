"""WireGuard capability plugin for the Freebox VPN server."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

from plugin.plugin import Plugin
from plugin.plugin_context import PluginContext
from plugin.plugin_manifest import PluginManifest
from plugin.plugin_runtime import PluginState
from plugins.wireguard.wireguard_check import WireGuardCheck
from plugins.wireguard.wireguard_config import WireGuardConfig

if TYPE_CHECKING:
    from observer.observer_result import ObserverResult


class WireGuardPlugin(Plugin):
    """Plugin responsible for checking the Freebox WireGuard server."""

    def __init__(
        self,
        *,
        check: WireGuardCheck | None = None,
        config: WireGuardConfig | None = None,
    ) -> None:
        self._state = PluginState.LOADED
        self._check = check or WireGuardCheck()
        self.config = config or WireGuardConfig()

    @property
    def name(self) -> str:
        return "wireguard"

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def manifest(self) -> PluginManifest:
        """Return the WireGuard plugin manifest."""
        return PluginManifest(
            name="wireguard",
            version="0.2.0",
            description="Freebox WireGuard VPN server health plugin for Ohana-Agent.",
        )

    def register(self, context: PluginContext) -> None:
        """Register the WireGuard plugin in the Ohana-Agent context."""
        del context
        self._state = PluginState.REGISTERED

    def execute(self, **kwargs: Any) -> ObserverResult:
        """Inspect one Freebox WireGuard server through the common plugin API."""
        from observer.observer_result import ObserverResult

        service_name = kwargs.get("service_id")
        base_url = kwargs.get("base_url")
        server_name = kwargs.get("server_name", "wireguard")

        if not isinstance(service_name, str) or not service_name.strip():
            raise ValueError(
                "WireGuardPlugin.execute() requires a non-empty 'service_id' argument."
            )

        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError(
                "WireGuardPlugin.execute() requires a non-empty 'base_url' argument."
            )

        if not isinstance(server_name, str) or not server_name.strip():
            raise ValueError(
                "WireGuardPlugin.execute() requires a non-empty 'server_name' argument."
            )

        started_at = perf_counter()
        result = self._check.check(
            service_name.strip(),
            base_url.strip(),
            server_name=server_name.strip(),
            app_id=self.config.app_id,
            app_version=self.config.app_version,
            app_token=self.config.app_token,
            timeout=self.config.timeout,
            retries=self.config.retries,
            verify_tls=self.config.verify_tls,
        )
        elapsed_ms = (perf_counter() - started_at) * 1000
        message = (
            "The Freebox WireGuard server is started"
            + (
                f" with {result.connection_count} active connection(s)."
                if result.connection_count is not None
                else "."
            )
            if result.healthy
            else result.error or "The Freebox WireGuard server is unavailable."
        )

        return ObserverResult(
            success=result.healthy,
            latency=elapsed_ms,
            message=message,
            check="wireguard.status",
            description="Check the WireGuard VPN server state through Freebox OS.",
            metadata={
                "service_id": result.service_name,
                "base_url": result.base_url,
                "server_name": result.server_name,
                "state": result.state,
                "connection_count": result.connection_count,
                "authenticated_connection_count": (
                    result.authenticated_connection_count
                ),
                "attempts": result.attempts,
                "verify_tls": self.config.verify_tls,
                "error": result.error,
            },
        )

    def reconfigure(self, config: WireGuardConfig) -> None:
        """Replace Freebox services and credentials without recreating the plugin."""
        self.config = config
