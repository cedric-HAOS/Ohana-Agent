"""Plugin execution bridge for the observation engine."""

from dataclasses import dataclass
from typing import Any

from observer.events import ObservationPublished
from observer.observation_engine import ObservationEngine
from plugin.plugin_command import PluginCommand
from plugin.plugin_manager import PluginManager


@dataclass(slots=True)
class PluginObservationExecutor:
    """Execute registered plugins and process their observation results."""

    plugin_manager: PluginManager
    observation_engine: ObservationEngine

    def execute(
        self,
        plugin_name: str,
        *,
        target_name: str,
        arguments: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> ObservationPublished:
        """Execute a plugin and publish its resulting observation."""
        plugin = self.plugin_manager.get(plugin_name)

        result = plugin.execute(**(arguments or {}))

        return self.observation_engine.process_result(
            result,
            target_name=target_name,
            source=source,
        )

    def execute_command(
        self,
        command: PluginCommand,
    ) -> ObservationPublished:
        """Execute a structured plugin command."""
        return self.execute(
            command.plugin_name,
            target_name=command.target_name,
            arguments=command.arguments,
        )
