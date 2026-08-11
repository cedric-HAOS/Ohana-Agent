"""Load the HAOS backup plugin configuration."""

from pathlib import Path

import yaml

from configuration.backup import BackupPluginConfig


class BackupConfigLoader:
    """Load and validate backup YAML configuration."""

    def load(self, path: str | Path) -> BackupPluginConfig:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return BackupPluginConfig.model_validate(data)
