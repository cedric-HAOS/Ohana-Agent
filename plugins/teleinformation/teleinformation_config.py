"""Runtime configuration used by the Téléinformation plugin."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TeleinformationServiceConfig:
    """One Linky service in direct or legacy Home Assistant mode."""

    name: str
    label: str
    node_id: str
    meter_id: str | None = None
    source_id: str = "rpi-linky"
    apparent_power_entity_id: str | None = None
    tariff_entity_id: str | None = None
    blue_off_peak_entity_id: str | None = None
    blue_peak_entity_id: str | None = None
    white_off_peak_entity_id: str | None = None
    white_peak_entity_id: str | None = None
    red_off_peak_entity_id: str | None = None
    red_peak_entity_id: str | None = None
    maximum_age_seconds: int = 30
    enabled: bool = True

    @property
    def index_entity_ids(self) -> dict[str, str]:
        values = {
            "blue_off_peak": self.blue_off_peak_entity_id,
            "blue_peak": self.blue_peak_entity_id,
            "white_off_peak": self.white_off_peak_entity_id,
            "white_peak": self.white_peak_entity_id,
            "red_off_peak": self.red_off_peak_entity_id,
            "red_peak": self.red_peak_entity_id,
        }
        return {name: entity_id for name, entity_id in values.items() if entity_id}


@dataclass(frozen=True, slots=True)
class TeleinformationConfig:
    """Runtime configuration for Linky Téléinformation checks."""

    services: list[TeleinformationServiceConfig] = field(default_factory=list)
    mode: str = "home_assistant"
    listen_host: str = "0.0.0.0"
    listen_port: int = 8770
    ingestion_token: str | None = None
    ingestion_token_environment_variable: str | None = (
        "OHANA_TELEINFORMATION_INGESTION_TOKEN"
    )
    home_assistant_url: str = "http://ha-green.ohana.lan:8123"
    access_token: str | None = None
    access_token_environment_variable: str | None = "OHANA_HOME_ASSISTANT_TOKEN"
    timeout: float = 5.0
    retries: int = 1
    maximum_age_seconds: int = 30
    verify_tls: bool = True
