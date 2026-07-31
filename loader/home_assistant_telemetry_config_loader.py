"""Load the Home Assistant telemetry plugin configuration."""

from pathlib import Path

import yaml

from configuration.home_assistant_telemetry import (
    HomeAssistantTelemetryPluginConfig,
)


class HomeAssistantTelemetryConfigLoader:
    """Load and validate the Home Assistant telemetry YAML configuration."""

    def load(self, path: str | Path) -> HomeAssistantTelemetryPluginConfig:
        file_path = Path(path)
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        return HomeAssistantTelemetryPluginConfig.model_validate(data)
