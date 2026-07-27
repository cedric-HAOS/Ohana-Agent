"""MQTT observation plugin configuration loader."""

from pathlib import Path

import yaml

from configuration.mqtt_plugin import MQTTPluginConfig


class MQTTConfigLoader:
    """Load declarative MQTT plugin configuration from YAML."""

    def load(self, path: str | Path) -> MQTTPluginConfig:
        """Load and validate an MQTT plugin configuration."""
        file_path = Path(path)
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        return MQTTPluginConfig.model_validate(data)
