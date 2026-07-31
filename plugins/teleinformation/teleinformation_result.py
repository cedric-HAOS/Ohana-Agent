"""Results exposed by the Téléinformation check."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TeleinformationValue:
    """One validated Linky value from Home Assistant or a direct frame."""

    entity_id: str
    value: float | None = None
    unit: str | None = None
    reported_at: datetime | None = None
    age_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class TeleinformationTariff:
    """Current Tempo tariff derived from the Linky NTARF value."""

    number: int
    color: str
    period: str
    label: str
    index_key: str
    index_label: str = ""


@dataclass(frozen=True, slots=True)
class TeleinformationCheckResult:
    """Freshness and current tariff result for one Linky meter."""

    meter_name: str
    healthy: bool
    apparent_power: TeleinformationValue
    tariff_value: TeleinformationValue
    tariff: TeleinformationTariff | None = None
    indexes: dict[str, TeleinformationValue] = field(default_factory=dict)
    active_index: TeleinformationValue | None = None
    attempts: int = 1
    error: str | None = None
    mode: str = "home_assistant"
    source_id: str | None = None
    meter_id: str | None = None
