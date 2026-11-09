"""Smart plug plugin: configuration, Home Assistant client and self-test.

The plugin never decides anything: ``PowerPlugController`` (core) asks it to read
the plug and to switch it, and reads its policy at every decision, so a change
saved in Vision applies at once.
"""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any

from ohana_agent.configuration.power_plug import PowerPlugPluginConfig
from ohana_agent.infrastructure.enums import HealthStatus
from ohana_agent.jobs.power_plug import PlugPolicy, PlugReading, PowerPlugError
from ohana_agent.observation import ObserverResult
from ohana_agent.plugins.power_plug.client import HomeAssistantPlug
from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_context import PluginContext
from ohana_agent.plugins.runtime.plugin_manifest import PluginManifest
from ohana_agent.plugins.runtime.plugin_runtime import PluginState

ClientFactory = Callable[[PowerPlugPluginConfig], HomeAssistantPlug]


def _home_assistant_client(config: PowerPlugPluginConfig) -> HomeAssistantPlug:
    assert config.home_assistant_url is not None  # noqa: S101 - validated
    assert config.access_token is not None  # noqa: S101 - validated
    assert config.switch_entity_id is not None  # noqa: S101 - validated
    return HomeAssistantPlug(
        url=config.home_assistant_url,
        token=config.access_token,
        switch_entity_id=config.switch_entity_id,
        power_entity_id=config.power_entity_id,
        verify_tls=config.verify_tls,
    )


class PowerPlugPlugin(Plugin):
    """The smart plug feeding Katsuyu's PC."""

    def __init__(
        self,
        *,
        config: PowerPlugPluginConfig | None = None,
        client_factory: ClientFactory = _home_assistant_client,
    ) -> None:
        self.config = config or PowerPlugPluginConfig()
        self._client_factory = client_factory
        self._client: HomeAssistantPlug | None = None
        self._state = PluginState.LOADED

    @property
    def name(self) -> str:
        return "power_plug"

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name=self.name,
            version="0.1.0",
            description=(
                "Prise connectée qui alimente le PC de Katsuyu le temps d'un cycle."
            ),
        )

    def register(self, context: PluginContext) -> None:
        del context
        self._state = PluginState.REGISTERED

    def reconfigure(self, config: PowerPlugPluginConfig) -> None:
        self.config = config
        self._client = None

    @property
    def active(self) -> bool:
        return self.config.enabled

    def policy(self) -> PlugPolicy | None:
        """The timings to apply, or ``None`` while the plug is off."""
        config = self.config
        if not config.enabled:
            return None
        return PlugPolicy(
            boot_delay_seconds=config.boot_delay_seconds,
            shutdown_grace_seconds=config.shutdown_grace_seconds,
            idle_watts=config.idle_watts,
            idle_confirm_seconds=config.idle_confirm_seconds,
            poll_seconds=config.poll_seconds,
        )

    # -- PowerPlug protocol, on the current configuration -----------------

    def read(self) -> PlugReading:
        return self._connected().read()

    def turn_on(self) -> None:
        self._connected().turn_on()

    def turn_off(self) -> None:
        self._connected().turn_off()

    def _connected(self) -> HomeAssistantPlug:
        config = self.config
        if not config.enabled:
            raise PowerPlugError("the power plug is disabled")
        if self._client is None:
            self._client = self._client_factory(config)
        return self._client

    # -- administration self-test -----------------------------------------

    def execute(self, **kwargs: Any) -> ObserverResult:
        """Read the plug without commanding it (the "Tester" button)."""
        del kwargs
        started = perf_counter()
        metadata: dict[str, Any] = {"read_only": True}
        try:
            if not self.config.enabled:
                raise PowerPlugError("la prise est désactivée")
            reading = self._connected().read()
        except PowerPlugError as error:
            return ObserverResult(
                success=False,
                latency=(perf_counter() - started) * 1000,
                check="power_plug.status",
                message=f"Prise illisible : {error}.",
                health=HealthStatus.UNKNOWN,
                metadata=metadata,
                description="Lire l'état de la prise de Bubule sans la commander.",
            )
        metadata["is_on"] = reading.is_on
        metadata["power_watts"] = reading.power_watts
        state = "allumée" if reading.is_on else "éteinte"
        watts = (
            f", {reading.power_watts:g} W"
            if reading.power_watts is not None
            else (
                " (pas de mesure de puissance)" if self.config.power_entity_id else ""
            )
        )
        return ObserverResult(
            success=True,
            latency=(perf_counter() - started) * 1000,
            check="power_plug.status",
            message=f"Prise {state}{watts}.",
            health=HealthStatus.HEALTHY,
            metadata=metadata,
            description="Lire l'état de la prise de Bubule sans la commander.",
        )
