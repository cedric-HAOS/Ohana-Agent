"""Runtime configuration used by Home Assistant telemetry."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class HomeAssistantTelemetryServiceConfig:
    """Home Assistant entities used to observe one infrastructure service."""

    name: str
    label: str
    node_id: str
    primary_entity_id: str
    secondary_entity_id: str | None = None
    maximum_age_seconds: int = 900
    enabled: bool = True

    @property
    def power_entity_id(self) -> str:
        """Deprecated alias for primary_entity_id."""
        return self.primary_entity_id

    @property
    def energy_entity_id(self) -> str | None:
        """Deprecated alias for secondary_entity_id."""
        return self.secondary_entity_id


@dataclass(frozen=True, slots=True)
class HomeAssistantTelemetryConfig:
    """Runtime configuration for Home Assistant entity freshness checks."""

    services: list[HomeAssistantTelemetryServiceConfig] = field(default_factory=list)
    home_assistant_url: str = "http://ha-green.ohana.lan:8123"
    access_token: str | None = None
    access_token_environment_variable: str | None = "OHANA_HOME_ASSISTANT_TOKEN"
    timeout: float = 5.0
    retries: int = 1
    maximum_age_seconds: int = 900
    verify_tls: bool = True
