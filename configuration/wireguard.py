"""WireGuard observation plugin configuration models."""

from pydantic import Field, PositiveFloat, PositiveInt, field_validator

from configuration.base import Config


class WireGuardPluginConfig(Config):
    """Declarative configuration for the Freebox WireGuard plugin."""

    enabled: bool = True
    timeout: PositiveFloat = 3.0
    retries: int = Field(default=1, ge=0)
    interval_seconds: PositiveInt = 60
    app_id: str = "fr.ohana.agent"
    app_version: str = "1.8.1"
    app_token: str | None = None
    verify_tls: bool = False

    @field_validator("app_id", "app_version")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("WireGuard Freebox credentials must not be empty.")

        return normalized

    @field_validator("app_token")
    @classmethod
    def normalize_app_token(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None
