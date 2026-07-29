"""Téléinformation plugin configuration loader."""

from pathlib import Path

import yaml

from configuration.teleinformation import TeleinformationPluginConfig


class TeleinformationConfigLoader:
    """Load declarative Téléinformation configuration from YAML."""

    def load(self, path: str | Path) -> TeleinformationPluginConfig:
        """Load and validate a Téléinformation plugin configuration."""
        file_path = Path(path)
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        return TeleinformationPluginConfig.model_validate(data)
