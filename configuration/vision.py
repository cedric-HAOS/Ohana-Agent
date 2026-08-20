"""Ohana-Vision export configuration."""

from pathlib import Path

from pydantic import Field, HttpUrl, PositiveFloat

from configuration.base import Config


class VisionConfig(Config):
    """Configuration used to export data to Ohana-Vision."""

    enabled: bool = True

    observation_url: HttpUrl = Field(
        default=HttpUrl("http://127.0.0.1:8000/api/observations")
    )

    infrastructure_url: HttpUrl = Field(
        default=HttpUrl("http://127.0.0.1:8000/api/infrastructure")
    )

    timeout_seconds: PositiveFloat = 5.0
    infrastructure_retry_seconds: PositiveFloat = 10.0
    infrastructure_refresh_seconds: PositiveFloat = 300.0
    outbox_path: Path | None = None
    outbox_retry_seconds: PositiveFloat = 10.0
    outbox_max_entries: int = Field(default=50_000, ge=1000, le=250_000)
