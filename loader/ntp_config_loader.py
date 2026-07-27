"""NTP plugin configuration loader."""

from pathlib import Path

import yaml

from configuration.ntp import NTPPluginConfig


class NTPConfigLoader:
    """Load declarative NTP plugin configuration from YAML."""

    def load(self, path: str | Path) -> NTPPluginConfig:
        """Load and validate an NTP plugin configuration."""
        file_path = Path(path)
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        return NTPPluginConfig.model_validate(data)
