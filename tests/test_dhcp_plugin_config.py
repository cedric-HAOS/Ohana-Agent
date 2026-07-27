import pytest
from pydantic import ValidationError

from configuration.dhcp import DHCPPluginConfig


def test_dhcp_plugin_config_defaults() -> None:
    config = DHCPPluginConfig()

    assert config.enabled is True
    assert config.check_service_active is True
    assert config.timeout == 3.0
    assert config.interval_seconds == 60
    assert config.policy.maximum_pool_usage_percent == 90.0


def test_dhcp_plugin_config_accepts_disabled_status_check() -> None:
    config = DHCPPluginConfig.model_validate(
        {
            "check_service_active": False,
        }
    )

    assert config.check_service_active is False


@pytest.mark.parametrize(
    "payload",
    [
        {"policy": {"maximum_pool_usage_percent": 0}},
        {"policy": {"maximum_pool_usage_percent": 101}},
        {"service_status_command": ["/bin/false"]},
        {"main_config_path": "/tmp/other.conf"},
    ],
)
def test_dhcp_plugin_config_rejects_invalid_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        DHCPPluginConfig.model_validate(payload)
