from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from ohana_agent.plugins.runtime.plugin_context import PluginContext
from ohana_agent.plugins.runtime.plugin_manifest import PluginManifest

if TYPE_CHECKING:
    from ohana_agent.observation.observer_result import ObserverResult


class Plugin(ABC):
    """Base contract for every Ohana-Agent plugin."""

    @property
    @abstractmethod
    def manifest(self) -> PluginManifest:
        """Return the plugin manifest."""

    @abstractmethod
    def register(self, context: PluginContext) -> None:
        """Register the plugin."""

    @abstractmethod
    def execute(
        self,
        **kwargs: Any,
    ) -> ObserverResult:
        """Execute the primary capability of the plugin."""
