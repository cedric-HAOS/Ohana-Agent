"""NTP capability plugin."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

from plugin.plugin import Plugin
from plugin.plugin_context import PluginContext
from plugin.plugin_manifest import PluginManifest
from plugin.plugin_runtime import PluginState
from plugins.ntp.ntp_check import NTPCheck
from plugins.ntp.ntp_check_result import NTPCheckResult
from plugins.ntp.ntp_config import NTPConfig

if TYPE_CHECKING:
    from observer.observer_result import ObserverResult


class NTPPlugin(Plugin):
    """Plugin responsible for NTP capability checks."""

    def __init__(
        self,
        *,
        check: NTPCheck | None = None,
        config: NTPConfig | None = None,
    ) -> None:
        self._state = PluginState.LOADED
        self._check = check or NTPCheck()
        self.config = config or NTPConfig()

    @property
    def name(self) -> str:
        return "ntp"

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def manifest(self) -> PluginManifest:
        """Return the NTP plugin manifest."""
        return PluginManifest(
            name="ntp",
            version="0.1.0",
            description="NTP capability plugin for Ohana-Agent.",
        )

    def register(self, context: PluginContext) -> None:
        """Register the NTP plugin in the Ohana-Agent context."""
        del context
        self._state = PluginState.REGISTERED

    def execute(self, **kwargs: Any) -> ObserverResult:
        """Execute an NTP query through the common plugin API."""
        from observer.observer_result import ObserverResult

        server = kwargs.get("server")

        if not isinstance(server, str) or not server.strip():
            raise ValueError(
                "NTPPlugin.execute() requires a non-empty 'server' argument."
            )

        port = kwargs.get("port", 123)

        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65_535
        ):
            raise ValueError(
                "NTPPlugin.execute() requires 'port' to be between 1 and 65535."
            )

        started_at = perf_counter()
        result = self.check(server.strip(), port=port)
        elapsed_ms = (perf_counter() - started_at) * 1000
        success, message = self._evaluate(result)

        return ObserverResult(
            success=success,
            latency=(
                result.round_trip_ms if result.round_trip_ms is not None else elapsed_ms
            ),
            message=message,
            check="ntp.query",
            description="Query an NTP server and evaluate clock synchronization.",
            metadata={
                "server": result.server,
                "port": result.port,
                "source_address": result.source_address,
                "offset_ms": result.offset_ms,
                "round_trip_ms": result.round_trip_ms,
                "stratum": result.stratum,
                "version": result.version,
                "leap_indicator": result.leap_indicator,
                "attempts": result.attempts,
                "error": result.error,
            },
        )

    def check(self, server: str, *, port: int = 123) -> NTPCheckResult:
        """Execute one configured NTP capability check."""
        return self._check.check(
            server,
            port=port,
            timeout=self.config.timeout,
            retries=self.config.retries,
        )

    def reconfigure(self, config: NTPConfig) -> None:
        """Replace NTP servers and policy without recreating the plugin."""
        self.config = config

    def _evaluate(self, result: NTPCheckResult) -> tuple[bool, str]:
        if not result.healthy:
            return False, result.error or f"NTP query failed for {result.server}."

        if result.offset_ms is None or result.stratum is None:
            return False, f"NTP response from {result.server} is incomplete."

        if abs(result.offset_ms) > self.config.policy.maximum_offset_ms:
            return (
                False,
                "NTP clock offset exceeds the configured threshold "
                f"for {result.server}: {result.offset_ms:.3f} ms.",
            )

        if result.stratum > self.config.policy.maximum_stratum:
            return (
                False,
                "NTP stratum exceeds the configured threshold "
                f"for {result.server}: {result.stratum}.",
            )

        return (
            True,
            f"NTP query succeeded for {result.server} "
            f"with an offset of {result.offset_ms:.3f} ms.",
        )
