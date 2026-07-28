"""WireGuard plugin configuration loader."""

from pathlib import Path

import yaml

from configuration.wireguard import WireGuardPluginConfig


class WireGuardConfigLoader:
    """Load declarative WireGuard plugin configuration from YAML."""

    def load(self, path: str | Path) -> WireGuardPluginConfig:
        """Load and validate a WireGuard plugin configuration."""
        file_path = Path(path)
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        return WireGuardPluginConfig.model_validate(data)
