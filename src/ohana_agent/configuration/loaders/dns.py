"""DNS plugin configuration loader."""

from pathlib import Path

import yaml

from ohana_agent.configuration.dns import DNSPluginConfig


class DNSConfigLoader:
    """Load declarative DNS plugin configuration from YAML."""

    def load(
        self,
        path: str | Path,
    ) -> DNSPluginConfig:
        """Load and validate a DNS plugin configuration."""
        file_path = Path(path)

        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}

        return DNSPluginConfig.model_validate(data)
