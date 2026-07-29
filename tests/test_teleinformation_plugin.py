"""Tests for the Linky Téléinformation observation plugin."""

from plugins.teleinformation.teleinformation_config import TeleinformationConfig
from plugins.teleinformation.teleinformation_plugin import TeleinformationPlugin
from plugins.teleinformation.teleinformation_result import (
    TeleinformationCheckResult,
    TeleinformationTariff,
    TeleinformationValue,
)


class FakeTeleinformationCheck:
    def check(self, *args, **kwargs) -> TeleinformationCheckResult:
        del args, kwargs
        return TeleinformationCheckResult(
            meter_name="Téléinformation Linky",
            healthy=True,
            apparent_power=TeleinformationValue(
                entity_id="sensor.teleinfo_041964385922_sinsts",
                value=1392.0,
                unit="VA",
            ),
            tariff_value=TeleinformationValue(
                entity_id="sensor.teleinfo_041964385922_ntarf",
                value=2.0,
            ),
            tariff=TeleinformationTariff(
                number=2,
                color="Bleue",
                period="HP",
                label="HP Bleue",
                index_key="blue_peak",
            ),
            indexes={
                "blue_peak": TeleinformationValue(
                    entity_id="sensor.teleinfo_041964385922_easf02",
                    value=6931422.0,
                    unit="Wh",
                )
            },
            active_index=TeleinformationValue(
                entity_id="sensor.teleinfo_041964385922_easf02",
                value=6931422.0,
                unit="Wh",
            ),
        )


def test_teleinformation_plugin_returns_service_observation() -> None:
    plugin = TeleinformationPlugin(
        check=FakeTeleinformationCheck(),
        config=TeleinformationConfig(access_token="secret"),
    )

    result = plugin.execute(
        service_id="teleinformation",
        service_name="Téléinformation Linky",
        node_id="linky-01",
        apparent_power_entity_id="sensor.teleinfo_041964385922_sinsts",
        tariff_entity_id="sensor.teleinfo_041964385922_ntarf",
        blue_peak_entity_id="sensor.teleinfo_041964385922_easf02",
        maximum_age_seconds=180,
    )

    assert result.success is True
    assert result.check == "teleinformation.freshness"
    assert result.metadata["service_id"] == "teleinformation"
    assert result.metadata["node_id"] == "linky-01"
    assert result.metadata["tariff_color"] == "Bleue"
    assert result.metadata["tariff_period"] == "HP"
    assert result.metadata["active_index"]["value"] == 6931422.0
    assert "1392 VA" in (result.message or "")
    assert "HP Bleue" in (result.message or "")
