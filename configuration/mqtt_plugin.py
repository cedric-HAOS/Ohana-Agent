"""MQTT observation plugin configuration models."""

from pathlib import Path

from pydantic import Field, PositiveFloat, PositiveInt, field_validator, model_validator

from configuration.base import Config


class MQTTPluginAuthenticationConfig(Config):
    """Credentials used by the MQTT observation plugin."""

    username: str | None = None
    password: str | None = None

    @field_validator("username")
    @classmethod
    def normalize_username(cls, username: str | None) -> str | None:
        if username is None:
            return None

        normalized = username.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_password_requires_username(self) -> "MQTTPluginAuthenticationConfig":
        if self.password is not None and self.username is None:
            raise ValueError("MQTT password requires a username.")

        return self


class MQTTPluginTLSConfig(Config):
    """TLS settings used by the MQTT observation plugin."""

    enabled: bool = False
    ca_file: Path | None = None
    insecure: bool = False

    @model_validator(mode="after")
    def validate_tls_options(self) -> "MQTTPluginTLSConfig":
        if not self.enabled and (self.ca_file is not None or self.insecure):
            raise ValueError("MQTT TLS options require TLS to be enabled.")

        return self


class MQTTPluginConfig(Config):
    """Declarative configuration for the MQTT observation plugin."""

    timeout: PositiveFloat = 5.0
    retries: int = Field(default=1, ge=0)
    interval_seconds: PositiveInt = 60
    keepalive_seconds: PositiveInt = 60
    client_id_prefix: str = "ohana-agent"
    topic_prefix: str = "ohana/agent/check"
    qos: int = Field(default=1, ge=0, le=2)
    authentication: MQTTPluginAuthenticationConfig = Field(
        default_factory=MQTTPluginAuthenticationConfig
    )
    tls: MQTTPluginTLSConfig = Field(default_factory=MQTTPluginTLSConfig)

    @field_validator("client_id_prefix")
    @classmethod
    def validate_client_id_prefix(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("MQTT client_id_prefix must not be empty.")

        return normalized

    @field_validator("topic_prefix")
    @classmethod
    def validate_topic_prefix(cls, value: str) -> str:
        normalized = value.strip().strip("/")

        if not normalized:
            raise ValueError("MQTT topic_prefix must not be empty.")

        if any(character in normalized for character in {"+", "#"}):
            raise ValueError("MQTT topic_prefix must not contain wildcards.")

        return normalized
