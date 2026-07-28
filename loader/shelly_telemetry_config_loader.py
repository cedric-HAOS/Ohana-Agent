"""Shelly telemetry plugin configuration loader."""

from pathlib import Path

import yaml

from configuration.shelly_telemetry import ShellyTelemetryPluginConfig


class ShellyTelemetryConfigLoader:
    """Load declarative Shelly telemetry configuration from YAML."""

    def load(self, path: str | Path) -> ShellyTelemetryPluginConfig:
        """Load and validate a Shelly telemetry plugin configuration."""
        file_path = Path(path)
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        return ShellyTelemetryPluginConfig.model_validate(data)
