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
    reported_at: str = "2026-07-29T09:59:30+00:00",
) -> HomeAssistantEntityState:
    return HomeAssistantEntityState(
        entity_id=entity_id,
        state=value,
        reported_at=reported_at,
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


def test_teleinformation_accepts_stale_ntarf_and_inactive_indexes() -> None:
    power = "sensor.teleinfo_041964385922_sinsts"
    tariff = "sensor.teleinfo_041964385922_ntarf"
    hc_blue = "sensor.teleinfo_041964385922_easf01"
    hp_blue = "sensor.teleinfo_041964385922_easf02"
    hc_white = "sensor.teleinfo_041964385922_easf03"
    stale_timestamp = "2026-07-28T22:00:00+00:00"
    client = FakeHomeAssistantClient(
        {
            power: state(power, "1392", unit="VA"),
            tariff: state(tariff, "2", reported_at=stale_timestamp),
            hc_blue: state(
                hc_blue,
                "43457535",
                unit="Wh",
                reported_at=stale_timestamp,
            ),
            hp_blue: state(hp_blue, "6931422", unit="Wh"),
            hc_white: state(
                hc_white,
                "1419917",
                unit="Wh",
                reported_at=stale_timestamp,
            ),
        }
    )

    result = TeleinformationCheck(client=client).check(
        "Compteur Linky",
        power,
        tariff,
        index_entity_ids={
            "blue_off_peak": hc_blue,
            "blue_peak": hp_blue,
            "white_off_peak": hc_white,
        },
        home_assistant_url="http://ha-green:8123",
        access_token="secret",
        access_token_environment_variable=None,
        maximum_age_seconds=180,
        retries=0,
        now=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
    )

    assert result.healthy is True
    assert result.tariff is not None
    assert result.tariff.index_key == "blue_peak"
    assert result.tariff_value.age_seconds == 43200.0
    assert result.indexes["blue_off_peak"].age_seconds == 43200.0
    assert result.active_index is not None
    assert result.active_index.entity_id == hp_blue


def test_teleinformation_allows_active_index_during_tariff_transition() -> None:
    power = "sensor.teleinfo_041964385922_sinsts"
    tariff = "sensor.teleinfo_041964385922_ntarf"
    hp_blue = "sensor.teleinfo_041964385922_easf02"
    client = FakeHomeAssistantClient(
        {
            power: state(power, "1392", unit="VA"),
            tariff: state(
                tariff,
                "2",
                reported_at="2026-07-29T09:59:50+00:00",
            ),
            hp_blue: state(
                hp_blue,
                "6931422",
                unit="Wh",
                reported_at="2026-07-28T22:00:00+00:00",
            ),
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
        retries=0,
        now=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
    )

    assert result.healthy is True
    assert result.active_index is not None
    assert result.active_index.age_seconds == 43200.0


def test_teleinformation_rejects_stale_active_index() -> None:
    power = "sensor.teleinfo_041964385922_sinsts"
    tariff = "sensor.teleinfo_041964385922_ntarf"
    hc_blue = "sensor.teleinfo_041964385922_easf01"
    hp_blue = "sensor.teleinfo_041964385922_easf02"
    stale_timestamp = "2026-07-29T09:50:00+00:00"
    client = FakeHomeAssistantClient(
        {
            power: state(power, "1392", unit="VA"),
            tariff: state(tariff, "2", reported_at="2026-07-28T22:00:00+00:00"),
            hc_blue: state(
                hc_blue,
                "43457535",
                unit="Wh",
                reported_at=stale_timestamp,
            ),
            hp_blue: state(
                hp_blue,
                "6931422",
                unit="Wh",
                reported_at=stale_timestamp,
            ),
        }
    )

    result = TeleinformationCheck(client=client).check(
        "Compteur Linky",
        power,
        tariff,
        index_entity_ids={
            "blue_off_peak": hc_blue,
            "blue_peak": hp_blue,
        },
        home_assistant_url="http://ha-green:8123",
        access_token="secret",
        access_token_environment_variable=None,
        maximum_age_seconds=180,
        retries=0,
        now=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
    )

    assert result.healthy is False
    assert hp_blue in (result.error or "")
    assert "has not reported" in (result.error or "")


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


def test_direct_teleinformation_uses_agent_reception_time() -> None:
    from plugins.teleinformation.teleinformation_frame_store import (
        TeleinformationFrameStore,
    )

    received_at = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    store = TeleinformationFrameStore()
    store.put(
        source="rpi-linky",
        meter_id="041964385922",
        received_at=received_at,
        frame={
            "SINSTS": {"raw": "01392", "value": 1392},
            "NTARF": {"raw": "02", "value": 2},
            "EASF02": {"raw": "006931422", "value": 6931422},
        },
    )

    result = TeleinformationCheck(frame_store=store).check_direct(
        "Téléinformation Linky",
        source_id="rpi-linky",
        meter_id="041964385922",
        maximum_age_seconds=30,
        now=datetime(2026, 7, 30, 10, 0, 10, tzinfo=UTC),
    )

    assert result.healthy is True
    assert result.mode == "direct_http"
    assert result.apparent_power.value == 1392
    assert result.tariff is not None
    assert result.tariff.label == "HP Bleue"
    assert result.active_index is not None
    assert result.active_index.entity_id == "EASF02"
    assert result.active_index.value == 6931422


def test_direct_teleinformation_rejects_stale_frame() -> None:
    from plugins.teleinformation.teleinformation_frame_store import (
        TeleinformationFrameStore,
    )

    store = TeleinformationFrameStore()
    store.put(
        source="rpi-linky",
        meter_id="041964385922",
        received_at=datetime(2026, 7, 30, 9, 59, tzinfo=UTC),
        frame={"SINSTS": 1392, "NTARF": 2, "EASF02": 6931422},
    )

    result = TeleinformationCheck(frame_store=store).check_direct(
        "Téléinformation Linky",
        source_id="rpi-linky",
        meter_id="041964385922",
        maximum_age_seconds=30,
        now=datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
    )

    assert result.healthy is False
    assert "60 secondes" in (result.error or "")
