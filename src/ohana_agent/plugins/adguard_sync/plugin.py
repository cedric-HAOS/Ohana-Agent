"""Publish synchronization evidence through the common observation pipeline."""

import subprocess
from time import perf_counter
from typing import Any

import httpx
import yaml

from ohana_agent.infrastructure.enums import HealthStatus
from ohana_agent.observation import ObserverResult
from ohana_agent.plugins.adguard_sync.config import AdGuardSyncConfig
from ohana_agent.plugins.adguard_sync.snapshot import AdGuardSnapshotProbe
from ohana_agent.plugins.adguard_sync.systemd import SystemdSyncProbe
from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_context import PluginContext
from ohana_agent.plugins.runtime.plugin_manifest import PluginManifest
from ohana_agent.plugins.runtime.plugin_runtime import PluginState

MESSAGES = {
    "healthy": (
        "Synchronisation AdGuard vérifiée ; "
        "les configurations répliquées correspondent."
    ),
    "units_missing": "Les unités de synchronisation AdGuard sont absentes.",
    "timer_inactive": "La planification de la synchronisation AdGuard est inactive.",
    "cycle_failed": "Le dernier cycle de synchronisation AdGuard a échoué.",
    "never_completed": "Aucun cycle AdGuard terminé depuis le démarrage du système.",
    "stale": "La synchronisation AdGuard dépasse le délai configuré.",
    "running": "Synchronisation AdGuard en cours ; comparaison différée.",
    "divergent": "Les configurations AdGuard divergent dans les sections contrôlées.",
    "unverifiable": "Contrôle AdGuard impossible ; vérifier les accès et la config.",
}


class AdGuardSyncPlugin(Plugin):
    def __init__(
        self,
        *,
        config: AdGuardSyncConfig,
        systemd: SystemdSyncProbe | None = None,
        snapshot: AdGuardSnapshotProbe | None = None,
    ) -> None:
        self.config = config
        self._systemd = systemd or SystemdSyncProbe()
        self._snapshot = snapshot or AdGuardSnapshotProbe()
        self._state = PluginState.LOADED

    @property
    def name(self) -> str:
        return "adguard_sync"

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name=self.name,
            version="0.1.0",
            description="Read-only AdGuard Home synchronization supervision.",
        )

    def register(self, context: PluginContext) -> None:
        del context
        self._state = PluginState.REGISTERED

    def reconfigure(self, config: AdGuardSyncConfig) -> None:
        self.config = config

    def execute(self, **kwargs: Any) -> ObserverResult:
        started = perf_counter()
        metadata: dict[str, Any] = {
            "service_id": kwargs.get("service_id"),
            "node_id": kwargs.get("node_id"),
            "read_only": True,
        }
        settings = self.config.settings
        state = "unverifiable"
        try:
            cycle = self._systemd.inspect(
                maximum_age_seconds=settings.maximum_age_seconds
            )
            metadata["cycle"] = cycle
            state = str(cycle["state"])
            if state == "fresh":
                comparison = self._snapshot.inspect(settings)
                after = self._systemd.inspect(
                    maximum_age_seconds=settings.maximum_age_seconds
                )
                # A new cycle invalidates a snapshot taken while rules change.
                if after["state"] != "fresh":
                    metadata["cycle"] = after
                    state = str(after["state"])
                elif after.get("last_completed_age_seconds", 0) < cycle.get(
                    "last_completed_age_seconds", 0
                ):
                    state = "running"
                else:
                    metadata.update(comparison)
                    state = (
                        "divergent" if comparison["different_sections"] else "healthy"
                    )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            subprocess.SubprocessError,
            httpx.HTTPError,
            yaml.YAMLError,
        ):
            # Never publish exception text, URLs, configuration or API bodies.
            state = "unverifiable"
        metadata["sync_state"] = state
        health = (
            HealthStatus.HEALTHY
            if state == "healthy"
            else HealthStatus.UNKNOWN
            if state in {"running", "unverifiable"}
            else HealthStatus.UNHEALTHY
        )
        return ObserverResult(
            success=state == "healthy",
            latency=(perf_counter() - started) * 1000,
            check="adguard_sync.status",
            message=MESSAGES[state],
            health=health,
            metadata=metadata,
            description="Vérifier le cycle et la cohérence de la réplication AdGuard.",
        )
