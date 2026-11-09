"""Configuration of the smart plug that feeds the Katsuyu PC."""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from ohana_agent.configuration.base import Config


class PowerPlugPluginConfig(Config):
    """Editable settings of the ``power_plug`` plugin (Home Assistant switch).

    The access token lives in this file, like the other plugin credentials: it is
    masked when the configuration is read and kept when it is saved blank.
    """

    enabled: bool = False
    home_assistant_url: str | None = Field(default=None, pattern=r"^https?://[^\s/]+")
    access_token: str | None = None
    switch_entity_id: str | None = Field(
        default=None, pattern=r"^switch\.[a-z0-9_]+$", max_length=120
    )
    # Optional: the load the plug measures. Lets Ohana cut only an idle PC.
    power_entity_id: str | None = Field(
        default=None, pattern=r"^sensor\.[a-z0-9_]+$", max_length=120
    )
    verify_tls: bool = True
    boot_delay_seconds: int = Field(default=15, ge=0, le=120)
    shutdown_grace_seconds: int = Field(default=300, ge=60, le=1800)
    idle_watts: float = Field(default=5.0, ge=0, le=50)
    idle_confirm_seconds: int = Field(default=30, ge=0, le=300)
    poll_seconds: int = Field(default=15, ge=5, le=300)

    @field_validator("home_assistant_url", "power_entity_id", "access_token")
    @classmethod
    def blank_is_missing(cls, value: str | None) -> str | None:
        """An emptied field means "not set", never an empty string."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("home_assistant_url")
    @classmethod
    def strip_trailing_slash(cls, value: str | None) -> str | None:
        return value.rstrip("/") if value else value

    @model_validator(mode="after")
    def validate_enabled_plug(self) -> PowerPlugPluginConfig:
        if self.enabled and not (
            self.home_assistant_url and self.access_token and self.switch_entity_id
        ):
            raise ValueError(
                "an enabled power plug requires home_assistant_url, access_token "
                "and switch_entity_id"
            )
        return self
