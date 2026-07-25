from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

from plugin.plugin import Plugin
from plugin.plugin_context import PluginContext
from plugin.plugin_manifest import PluginManifest
from plugin.plugin_runtime import PluginState
from plugins.dns.dns_capability_runtime import DNSCapabilityRuntime
from plugins.dns.dns_check import DNSCheck
from plugins.dns.dns_check_result import DNSCheckResult
from plugins.dns.dns_config import DNSConfig
from plugins.dns.dns_events import DNSCheckFailed, DNSCheckStarted, DNSCheckSucceeded
from plugins.dns.dns_runtime import DNSRuntime
from plugins.dns.dns_server import DNSServer
from plugins.dns.dns_statistics import DNSStatistics

if TYPE_CHECKING:
    from observer.observer_result import ObserverResult


class DNSPlugin(Plugin):
    """Plugin responsible for DNS capability checks."""

    def __init__(
        self,
        check: DNSCheck | None = None,
        event_bus: Any | None = None,
        runtime: DNSRuntime | None = None,
        config: DNSConfig | None = None,
        capability_runtime: DNSCapabilityRuntime | None = None,
    ) -> None:
        self._state = PluginState.LOADED
        self._check = check or DNSCheck()
        self._event_bus = event_bus
        self.runtime = runtime or DNSRuntime()
        self.config = config or DNSConfig()
        self.capability_runtime = capability_runtime or DNSCapabilityRuntime()
        self.servers = [
            DNSServer(config=server_config) for server_config in self.config.servers
        ]

    @property
    def name(self) -> str:
        return "dns"

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def manifest(self) -> PluginManifest:
        """Return the DNS plugin manifest."""
        return PluginManifest(
            name="dns",
            version="0.1.0",
            description="DNS capability plugin for Ohana-Agent.",
        )

    def register(self, context: PluginContext) -> None:
        """Register the DNS plugin in the Ohana-Agent context."""
        self._event_bus = context.event_bus
        self._state = PluginState.REGISTERED

    def execute(
        self,
        **kwargs: Any,
    ) -> ObserverResult:
        """Execute a DNS check through the common plugin API."""

        from observer.observer_result import ObserverResult

        hostname = kwargs.get("hostname")

        if not isinstance(hostname, str) or not hostname:
            raise ValueError(
                "DNSPlugin.execute() requires a non-empty 'hostname' argument."
            )

        server = kwargs.get("server")

        if server is not None and (not isinstance(server, str) or not server.strip()):
            raise ValueError(
                "DNSPlugin.execute() requires 'server' to be a non-empty string."
            )

        started_at = perf_counter()
        result = self.check(hostname, server=server)
        latency_ms = (perf_counter() - started_at) * 1000

        if result.healthy:
            message = f"DNS resolution succeeded for {result.hostname}."
        else:
            message = result.error or (f"DNS resolution failed for {result.hostname}.")

        return ObserverResult(
            success=result.healthy,
            latency=latency_ms,
            message=message,
            check="dns.resolve",
            description="Resolve a hostname using the DNS plugin.",
            metadata={
                "hostname": result.hostname,
                "server": result.server,
                "address": result.address,
                "error": result.error,
            },
        )

    def check(
        self,
        hostname: str,
        *,
        server: str | None = None,
    ) -> DNSCheckResult:
        self._publish(DNSCheckStarted(hostname=hostname))

        if server is None:
            result = self._check.check(hostname)
        else:
            result = self._check.check(hostname, server=server)

        if result.healthy:
            self.runtime.record_success(
                hostname=result.hostname,
                address=result.address,
            )
            self._publish(
                DNSCheckSucceeded(
                    hostname=result.hostname,
                    address=result.address,
                )
            )
        else:
            self.runtime.record_failure(
                hostname=result.hostname,
                error=result.error,
            )
            self._publish(
                DNSCheckFailed(
                    hostname=result.hostname,
                    error=result.error,
                )
            )

        return result

    def reconfigure(self, config: DNSConfig) -> None:
        """Replace DNS servers and policy without recreating the plugin."""
        self.config = config
        self.servers = [
            DNSServer(config=server_config) for server_config in config.servers
        ]

    def _publish(self, event: object) -> None:
        if self._event_bus is not None:
            self._event_bus.publish(event)

    def statistics(self) -> DNSStatistics:
        return DNSStatistics.from_runtime(self.runtime)

    def update_capability_runtime(self) -> DNSCapabilityRuntime:
        healthy_servers = sum(
            1 for server in self.servers if server.runtime.healthy is True
        )

        self.capability_runtime.update(
            total_servers=len(self.servers),
            healthy_servers=healthy_servers,
            minimum_healthy_servers=(self.config.policy.minimum_healthy_servers),
        )

        return self.capability_runtime

    def check_all(self) -> DNSCapabilityRuntime:
        for server in self.servers:
            if not server.enabled:
                continue

            for hostname in self.config.queries:
                server.check(hostname)

        return self.update_capability_runtime()
