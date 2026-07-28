"""Runtime configuration used by the Shelly telemetry plugin."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ShellyTelemetryDeviceConfig:
    """Home Assistant entities used to observe one Shelly device."""

    name: str
    power_entity_id: str
    energy_entity_id: str | None = None
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class ShellyTelemetryConfig:
    """Runtime configuration for Shelly telemetry freshness checks."""

    devices: list[ShellyTelemetryDeviceConfig] = field(default_factory=list)
    home_assistant_url: str = "http://ha-green.ohana.lan:8123"
    access_token: str | None = None
    access_token_environment_variable: str | None = "OHANA_HOME_ASSISTANT_TOKEN"
    timeout: float = 5.0
    retries: int = 1
    maximum_age_seconds: int = 900
    verify_tls: bool = True
