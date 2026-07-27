"""Network presence plugin configuration loader."""

from pathlib import Path

import yaml

from configuration.network import NetworkPluginConfig


class NetworkConfigLoader:
    """Load declarative network presence configuration from YAML."""

    def load(self, path: str | Path) -> NetworkPluginConfig:
        """Load and validate a network presence configuration."""
        file_path = Path(path)
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        return NetworkPluginConfig.model_validate(data)
