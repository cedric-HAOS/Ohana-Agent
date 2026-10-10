"""Load optional AdGuard supervision without breaking existing installations."""

from pathlib import Path

import yaml

from ohana_agent.configuration.adguard_sync import AdGuardSyncPluginConfig


class AdGuardSyncConfigLoader:
    def load(self, path: str | Path) -> AdGuardSyncPluginConfig:
        file_path = Path(path)
        if not file_path.exists():
            return AdGuardSyncPluginConfig()
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        return AdGuardSyncPluginConfig.model_validate(data)
