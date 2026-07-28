"""Z-Wave plugin configuration loader."""

from pathlib import Path

import yaml

from configuration.zwave import ZWavePluginConfig


class ZWaveConfigLoader:
    """Load declarative Z-Wave plugin configuration from YAML."""

    def load(self, path: str | Path) -> ZWavePluginConfig:
        """Load and validate a Z-Wave plugin configuration."""
        file_path = Path(path)
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        return ZWavePluginConfig.model_validate(data)
