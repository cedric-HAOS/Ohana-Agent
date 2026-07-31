"""Téléinformation observation plugin configuration models."""

from typing import Literal

from pydantic import Field, PositiveFloat, PositiveInt, field_validator, model_validator

from configuration.base import Config


class TeleinformationPluginConfig(Config):
    """Direct teleinfo2mqtt ingestion with one-version Home Assistant fallback."""

    enabled: bool = True
    mode: Literal["direct_http", "home_assistant"] = "home_assistant"
    timeout: PositiveFloat = 5.0
    retries: int = Field(default=1, ge=0)
    interval_seconds: PositiveInt = 30
    maximum_age_seconds: PositiveInt = 30

    listen_host: str = "0.0.0.0"
    listen_port: int = Field(default=8770, ge=1, le=65535)
    ingestion_token: str | None = None
    ingestion_token_environment_variable: str | None = (
        "OHANA_TELEINFORMATION_INGESTION_TOKEN"
    )

    # Compatibility mode retained for migrations from Agent 1.8/1.9.
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

    @field_validator("listen_host")
    @classmethod
    def normalize_listen_host(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("listen_host must not be empty.")
        return normalized

    @field_validator(
        "ingestion_token",
        "ingestion_token_environment_variable",
        "access_token",
        "access_token_environment_variable",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_token_source(self) -> "TeleinformationPluginConfig":
        if self.mode == "direct_http":
            if (
                self.ingestion_token is None
                and self.ingestion_token_environment_variable is None
            ):
                raise ValueError(
                    "Direct Téléinformation requires an ingestion token or "
                    "environment variable."
                )
        elif (
            self.access_token is None and self.access_token_environment_variable is None
        ):
            raise ValueError(
                "Home Assistant Téléinformation requires an access token or "
                "environment variable."
            )
        return self
