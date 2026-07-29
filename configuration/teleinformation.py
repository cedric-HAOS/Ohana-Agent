"""Téléinformation observation plugin configuration models."""

from pydantic import Field, PositiveFloat, PositiveInt, field_validator, model_validator

from configuration.base import Config


class TeleinformationPluginConfig(Config):
    """Global Home Assistant connection and freshness policy."""

    enabled: bool = True
    timeout: PositiveFloat = 5.0
    retries: int = Field(default=1, ge=0)
    interval_seconds: PositiveInt = 60
    maximum_age_seconds: PositiveInt = 180
    home_assistant_url: str = "http://ha-green.ohana.lan:8123"
    access_token: str | None = None
    access_token_environment_variable: str | None = "OHANA_HOME_ASSISTANT_TOKEN"
    verify_tls: bool = True

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
    def validate_token_source(self) -> "TeleinformationPluginConfig":
        if self.access_token is None and self.access_token_environment_variable is None:
            raise ValueError(
                "Téléinformation requires an access token or environment variable."
            )

        return self
