"""Tests for Linky Téléinformation checks."""

from datetime import UTC, datetime

from plugins.teleinformation.teleinformation_check import TeleinformationCheck
from plugins.teleinformation.teleinformation_client import HomeAssistantEntityState


class FakeHomeAssistantClient:
    def __init__(self, states: dict[str, HomeAssistantEntityState]) -> None:
        self.states = states
        self.calls: list[str] = []

    def query_entity(
        self,
        base_url: str,
        entity_id: str,
        *,
        access_token: str,
        timeout: float,
        verify_tls: bool,
    ) -> HomeAssistantEntityState:
        del base_url, access_token, timeout, verify_tls
        self.calls.append(entity_id)
        return self.states[entity_id]


def state(
    entity_id: str,
    value: str,
    *,
    unit: str | None = None,
) -> HomeAssistantEntityState:
    return HomeAssistantEntityState(
        entity_id=entity_id,
        state=value,
        reported_at="2026-07-29T09:59:30+00:00",
        unit=unit,
    )


def test_teleinformation_resolves_tempo_tariff_and_active_index() -> None:
    power = "sensor.teleinfo_041964385922_sinsts"
    tariff = "sensor.teleinfo_041964385922_ntarf"
    hp_blue = "sensor.teleinfo_041964385922_easf02"
    client = FakeHomeAssistantClient(
        {
            power: state(power, "1392", unit="VA"),
            tariff: state(tariff, "2"),
            hp_blue: state(hp_blue, "6931422", unit="Wh"),
        }
    )

    result = TeleinformationCheck(client=client).check(
        "Compteur Linky",
        power,
        tariff,
        index_entity_ids={"blue_peak": hp_blue},
        home_assistant_url="http://ha-green:8123",
        access_token="secret",
        access_token_environment_variable=None,
        maximum_age_seconds=180,
        now=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
    )

    assert result.healthy is True
    assert result.apparent_power.value == 1392.0
    assert result.tariff is not None
    assert result.tariff.number == 2
    assert result.tariff.color == "Bleue"
    assert result.tariff.period == "HP"
    assert result.tariff.label == "HP Bleue"
    assert result.active_index is not None
    assert result.active_index.value == 6931422.0


def test_teleinformation_rejects_stale_apparent_power() -> None:
    power = "sensor.teleinfo_041964385922_sinsts"
    tariff = "sensor.teleinfo_041964385922_ntarf"
    client = FakeHomeAssistantClient(
        {
            power: HomeAssistantEntityState(
                entity_id=power,
                state="1392",
                reported_at="2026-07-29T09:50:00+00:00",
                unit="VA",
            ),
            tariff: state(tariff, "2"),
        }
    )

    result = TeleinformationCheck(client=client).check(
        "Compteur Linky",
        power,
        tariff,
        home_assistant_url="http://ha-green:8123",
        access_token="secret",
        access_token_environment_variable=None,
        maximum_age_seconds=180,
        retries=0,
        now=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
    )

    assert result.healthy is False
    assert "has not reported" in (result.error or "")


def test_teleinformation_rejects_unknown_ntarf_value() -> None:
    power = "sensor.teleinfo_041964385922_sinsts"
    tariff = "sensor.teleinfo_041964385922_ntarf"
    client = FakeHomeAssistantClient(
        {
            power: state(power, "1392", unit="VA"),
            tariff: state(tariff, "7"),
        }
    )

    result = TeleinformationCheck(client=client).check(
        "Compteur Linky",
        power,
        tariff,
        home_assistant_url="http://ha-green:8123",
        access_token="secret",
        access_token_environment_variable=None,
        maximum_age_seconds=180,
        retries=0,
        now=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
    )

    assert result.healthy is False
    assert "invalid NTARF" in (result.error or "")
