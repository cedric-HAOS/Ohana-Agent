"""Build Shelly telemetry runtime configuration."""

from configuration.shelly_telemetry import ShellyTelemetryPluginConfig
from plugins.shelly_telemetry.shelly_telemetry_config import (
    ShellyTelemetryConfig,
    ShellyTelemetryDeviceConfig,
)


class ShellyTelemetryConfigurationBuilder:
    """Convert validated Shelly plugin configuration to runtime objects."""

    def build(
        self,
        config: ShellyTelemetryPluginConfig,
    ) -> ShellyTelemetryConfig:
        """Build the runtime configuration without duplicating infrastructure data."""
        return ShellyTelemetryConfig(
            devices=[
                ShellyTelemetryDeviceConfig(
                    name=device.name,
                    power_entity_id=device.power_entity_id,
                    energy_entity_id=device.energy_entity_id,
                    enabled=device.enabled,
                )
                for device in config.devices
            ],
            home_assistant_url=config.home_assistant_url,
            access_token=config.access_token,
            access_token_environment_variable=(
                config.access_token_environment_variable
            ),
            timeout=config.timeout,
            retries=config.retries,
            maximum_age_seconds=config.maximum_age_seconds,
            verify_tls=config.verify_tls,
        )
