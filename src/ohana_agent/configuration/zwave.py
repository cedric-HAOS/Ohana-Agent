"""Z-Wave observation plugin configuration models."""

from pydantic import Field, PositiveFloat, PositiveInt

from ohana_agent.configuration.base import Config


class ZWavePluginConfig(Config):
    """Declarative configuration for the Z-Wave health plugin."""

    enabled: bool = True
    timeout: PositiveFloat = 3.0
    retries: int = Field(default=1, ge=0)
    interval_seconds: PositiveInt = 60
    verify_tls: bool = True
    # Minutes without any contact before a node is flagged. None disables the
    # check. Battery nodes (can_sleep) wake rarely, so they have their own delay.
    last_seen_alert_minutes: PositiveInt | None = None
    sleeping_last_seen_alert_minutes: PositiveInt | None = None
