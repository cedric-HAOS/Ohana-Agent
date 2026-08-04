"""Dispatcher bridge for plugin observation execution."""

from dataclasses import dataclass
from datetime import datetime

from infrastructure.enums import HealthStatus
from observer.events import ObservationPublished
from observer.observer_result import ObserverResult
from observer.plugin_observation_executor import (
    PluginObservationExecutor,
)
from plugin.plugin_command import PluginCommand

_OBSERVATION_SOURCES = {
    "home_assistant_telemetry.freshness": "home_assistant.telemetry.freshness",
}


@dataclass(slots=True)
class PluginObservationDispatcher:
    """Dispatch plugin commands through the observation execution pipeline."""

    executor: PluginObservationExecutor

    def execute(
        self,
        command: str,
        arguments: dict[str, object] | None = None,
    ) -> ObservationPublished:
        """Parse and execute a plugin command."""
        plugin_command = self.parse(
            command,
            arguments=arguments,
        )

        return self.executor.execute_command(plugin_command)

    def publish_suspended(
        self,
        command: str,
        arguments: dict[str, object],
        *,
        reason: str,
        next_activation: datetime | None,
    ) -> ObservationPublished:
        """Publish an explicit suspended observation for one scheduled target."""
        plugin_command = self.parse(command, arguments=arguments)
        observation_source = _OBSERVATION_SOURCES.get(command, command)
        metadata = dict(arguments)
        device_id = metadata.get("device_id")
        if isinstance(device_id, str) and device_id.strip():
            # The plugin normally adds this discriminator to its result. A
            # suspended task bypasses plugin execution, so preserve the same
            # routing information explicitly.
            metadata["target_type"] = "device"
            metadata["device_id"] = device_id.strip()
        metadata["monitoring_suspended"] = True
        metadata["next_activation"] = (
            next_activation.isoformat() if next_activation is not None else None
        )
        result = ObserverResult(
            success=True,
            latency=0.0,
            message=reason,
            check=observation_source,
            description="Surveillance suspendue par la plage horaire de l'équipement.",
            metadata=metadata,
            health=HealthStatus.SUSPENDED,
        )
        return self.executor.observation_engine.process_result(
            result,
            target_name=plugin_command.target_name,
            source=observation_source,
        )

    @staticmethod
    def parse(
        command: str,
        *,
        arguments: dict[str, object] | None = None,
    ) -> PluginCommand:
        """Convert a dotted command into a structured plugin command."""
        normalized_command = command.strip()

        if not normalized_command:
            raise ValueError("Plugin command must not be empty.")

        plugin_name, separator, operation = normalized_command.partition(".")

        if not separator or not plugin_name or not operation:
            raise ValueError(
                "Plugin command must use the '<plugin>.<operation>' format."
            )

        resolved_arguments = dict(arguments or {})
        service_id = resolved_arguments.get("service_id")
        device_id = resolved_arguments.get("device_id")

        if isinstance(service_id, str) and service_id.strip():
            target_name = service_id.strip()
        elif isinstance(device_id, str) and device_id.strip():
            target_name = device_id.strip()
        else:
            target_name = plugin_name

        return PluginCommand(
            plugin_name=plugin_name,
            operation=operation,
            target_name=target_name,
            arguments=resolved_arguments,
        )
