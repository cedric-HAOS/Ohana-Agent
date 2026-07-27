"""Network presence plugin configuration models."""

from pydantic import Field, PositiveFloat, PositiveInt

from configuration.base import Config


class NetworkPluginConfig(Config):
    """Declarative configuration for network device presence checks."""

    enabled: bool = True
    timeout: PositiveFloat = 1.0
    retries: int = Field(default=0, ge=0)
    interval_seconds: PositiveInt = 60
    failure_threshold: PositiveInt = 3
