"""Load the optional smart plug configuration (absent file = plug disabled)."""

from __future__ import annotations

from pathlib import Path

import yaml

from ohana_agent.configuration.power_plug import PowerPlugPluginConfig


class PowerPlugConfigLoader:
    """Existing installations have no power-plug.yaml until an update brings it."""

    def load(self, path: str | Path) -> PowerPlugPluginConfig:
        file_path = Path(path)
        if not file_path.exists():
            return PowerPlugPluginConfig()
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        return PowerPlugPluginConfig.model_validate(data)
