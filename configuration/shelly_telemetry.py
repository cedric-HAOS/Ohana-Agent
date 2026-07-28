"""Shelly telemetry observation plugin configuration models."""

from pydantic import Field, PositiveFloat, PositiveInt, field_validator, model_validator

from configuration.base import Config


class ShellyTelemetryDevicePluginConfig(Config):
    """Legacy global Shelly mapping accepted during configuration migration."""

    name: str
    power_entity_id: str
    energy_entity_id: str | None = None
    enabled: bool = True

    @field_validator("name", "power_entity_id")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("Shelly telemetry fields must not be empty.")

        return normalized

    @field_validator("energy_entity_id")
    @classmethod
    def normalize_optional_entity(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_entity_ids(self) -> "ShellyTelemetryDevicePluginConfig":
        for entity_id in (self.power_entity_id, self.energy_entity_id):
            if entity_id is not None and "." not in entity_id:
                raise ValueError(f"Invalid Home Assistant entity id: {entity_id!r}.")

        return self


class ShellyTelemetryPluginConfig(Config):
    """Global Home Assistant connection and freshness policy."""

    enabled: bool = True
    timeout: PositiveFloat = 5.0
    retries: int = Field(default=1, ge=0)
    interval_seconds: PositiveInt = 300
    maximum_age_seconds: PositiveInt = 900
    home_assistant_url: str = "http://ha-green.ohana.lan:8123"
    access_token: str | None = None
    access_token_environment_variable: str | None = "OHANA_HOME_ASSISTANT_TOKEN"
    verify_tls: bool = True
    # Accepted only so an existing 1.7.0/1.7.1 configuration still starts.
    # Device mappings now live in topology device metadata and are omitted on save.
    devices: list[ShellyTelemetryDevicePluginConfig] = Field(
        default_factory=list,
        exclude=True,
        repr=False,
    )

    @field_validator("home_assistant_url")
    @classmethod
    def validate_home_assistant_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")

        if not normalized.startswith(("http://", "https://")):
            raise ValueError("home_assistant_url must start with http:// or https://.")

        return normalized

    @field_validator("access_token", "access_token_environment_variable")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_token_source(self) -> "ShellyTelemetryPluginConfig":
        if self.access_token is None and self.access_token_environment_variable is None:
            raise ValueError(
                "Shelly telemetry requires an access token or environment variable."
            )

        return self
