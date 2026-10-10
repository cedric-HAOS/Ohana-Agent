"""Configuration for read-only supervision of the local AdGuard sync cycle."""

from pathlib import Path
from typing import Any

from pydantic import Field, PositiveFloat, PositiveInt, model_validator

from ohana_agent.configuration.base import Config


class AdGuardSyncPluginConfig(Config):
    enabled: bool = False
    interval_seconds: PositiveInt = 60
    sync_config_path: Path = Path("/etc/ohana-agent/adguardhome-sync.yaml")
    timeout: PositiveFloat = Field(default=2.0, le=10)
    maximum_age_seconds: PositiveInt = 900

    @model_validator(mode="before")
    @classmethod
    def ignore_legacy_dns_probe_name(cls, value: Any) -> Any:
        """Accept existing configurations without exposing the removed DNS probe."""
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key != "dns_probe_name"}
        return value
