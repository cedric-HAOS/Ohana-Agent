"""Z-Wave observation plugin configuration models."""

from pydantic import Field, PositiveFloat, PositiveInt

from configuration.base import Config


class ZWavePluginConfig(Config):
    """Declarative configuration for the Z-Wave health plugin."""

    enabled: bool = True
    timeout: PositiveFloat = 3.0
    retries: int = Field(default=1, ge=0)
    interval_seconds: PositiveInt = 60
    verify_tls: bool = True
