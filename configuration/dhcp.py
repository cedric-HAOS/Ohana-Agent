"""DHCP observation plugin configuration models."""

from pydantic import Field, PositiveFloat, PositiveInt

from configuration.base import Config


class DHCPPolicyConfig(Config):
    """Health policy applied to the local DHCP pool."""

    maximum_pool_usage_percent: float = Field(default=90.0, gt=0, le=100)


class DHCPPluginConfig(Config):
    """Declarative configuration for the DHCP observation plugin."""

    enabled: bool = True
    check_service_active: bool = True
    timeout: PositiveFloat = 3.0
    interval_seconds: PositiveInt = 60
    policy: DHCPPolicyConfig = Field(default_factory=DHCPPolicyConfig)
