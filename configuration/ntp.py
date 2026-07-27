"""NTP plugin configuration models."""

from pydantic import Field, PositiveFloat, PositiveInt

from configuration.base import Config


class NTPPolicyConfig(Config):
    """Health policy applied to one NTP observation."""

    maximum_offset_ms: PositiveFloat = 1000.0
    maximum_stratum: int = Field(default=15, ge=1, le=15)


class NTPPluginConfig(Config):
    """Declarative configuration for the NTP plugin."""

    enabled: bool = True

    timeout: PositiveFloat = 2.0
    retries: int = Field(default=1, ge=0)
    interval_seconds: PositiveInt = 60
    policy: NTPPolicyConfig = Field(default_factory=NTPPolicyConfig)
