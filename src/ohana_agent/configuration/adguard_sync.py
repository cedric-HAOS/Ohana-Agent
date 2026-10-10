"""Configuration for read-only supervision of the local AdGuard sync cycle."""

from pathlib import Path

from pydantic import Field, PositiveFloat, PositiveInt

from ohana_agent.configuration.base import Config


class AdGuardSyncPluginConfig(Config):
    enabled: bool = False
    interval_seconds: PositiveInt = 60
    sync_config_path: Path = Path("/etc/ohana-agent/adguardhome-sync.yaml")
    timeout: PositiveFloat = Field(default=2.0, le=10)
    maximum_age_seconds: PositiveInt = 900
    dns_probe_name: str = Field(default="infra-01.ohana.lan", min_length=1)
