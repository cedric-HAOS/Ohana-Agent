"""DHCP observation plugin configuration loader."""

from pathlib import Path

import yaml

from configuration.dhcp import DHCPPluginConfig


class DHCPConfigLoader:
    """Load declarative DHCP plugin configuration from YAML."""

    def load(self, path: str | Path) -> DHCPPluginConfig:
        """Load and validate a DHCP plugin configuration."""
        file_path = Path(path)
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        return DHCPPluginConfig.model_validate(data)
