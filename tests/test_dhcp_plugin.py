from pathlib import Path

import pytest

from plugins.dhcp.dhcp_check_result import DHCPCheckResult
from plugins.dhcp.dhcp_config import (
    DHCPConfig,
    DHCPPolicyConfig,
    DHCPServerConfig,
)
from plugins.dhcp.dhcp_plugin import DHCPPlugin


class FakeDHCPCheck:
    def __init__(self, result: DHCPCheckResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def check(self, server: str, **kwargs: object) -> DHCPCheckResult:
        self.calls.append({"server": server, **kwargs})
        return self.result


def make_result(*, usage: float = 12.0, healthy: bool = True) -> DHCPCheckResult:
    return DHCPCheckResult(
        server="192.168.1.10",
        port=67,
        service_id="dhcp-primary",
        healthy=healthy,
        service_active=healthy,
        range_start="192.168.1.100",
        range_end="192.168.1.199",
        pool_size=100,
        lease_count=12,
        available_address_count=88,
        pool_usage_percent=usage,
        status_output="active" if healthy else "inactive",
        error=None if healthy else "DHCP service is not active: inactive",
    )


def make_config(*, threshold: float = 90.0) -> DHCPConfig:
    return DHCPConfig(
        servers=[
            DHCPServerConfig(
                name="dhcp-primary",
                address="192.168.1.10",
                port=67,
            )
        ],
        main_config_path=Path("/tmp/dnsmasq.conf"),
        leases_path=Path("/tmp/dnsmasq.leases"),
        service_status_command=None,
        timeout=1.5,
        policy=DHCPPolicyConfig(maximum_pool_usage_percent=threshold),
    )


def test_dhcp_plugin_returns_healthy_observation() -> None:
    check = FakeDHCPCheck(make_result())
    plugin = DHCPPlugin(check=check, config=make_config())

    result = plugin.execute(
        server="192.168.1.10",
        port=67,
        service_id="dhcp-primary",
    )

    assert result.success is True
    assert result.check == "dhcp.status"
    assert result.metadata["service_active"] is True
    assert result.metadata["lease_count"] == 12
    assert result.metadata["available_address_count"] == 88
    assert result.metadata["pool_size"] == 100
    assert result.metadata["pool_usage_percent"] == 12.0
    assert "12 active lease(s)" in result.message
    assert check.calls[0]["main_config_path"] == Path("/tmp/dnsmasq.conf")
    assert check.calls[0]["timeout"] == 1.5


def test_dhcp_plugin_reports_inactive_service() -> None:
    plugin = DHCPPlugin(
        check=FakeDHCPCheck(make_result(healthy=False)),
        config=make_config(),
    )

    result = plugin.execute(
        server="192.168.1.10",
        port=67,
        service_id="dhcp-primary",
    )

    assert result.success is False
    assert result.message == "DHCP service is not active: inactive"


def test_dhcp_plugin_reports_high_pool_usage() -> None:
    plugin = DHCPPlugin(
        check=FakeDHCPCheck(make_result(usage=85.0)),
        config=make_config(threshold=80.0),
    )

    result = plugin.execute(
        server="192.168.1.10",
        port=67,
        service_id="dhcp-primary",
    )

    assert result.success is False
    assert "exceeds the configured threshold" in result.message


def test_dhcp_plugin_reconfigure_replaces_runtime_config() -> None:
    plugin = DHCPPlugin(config=make_config())
    updated = make_config(threshold=70.0)

    plugin.reconfigure(updated)

    assert plugin.config is updated


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"port": 67, "service_id": "dhcp-primary"}, "server"),
        ({"server": "192.168.1.10", "port": 67}, "service_id"),
        (
            {
                "server": "192.168.1.10",
                "port": 0,
                "service_id": "dhcp-primary",
            },
            "port",
        ),
    ],
)
def test_dhcp_plugin_rejects_invalid_arguments(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        DHCPPlugin().execute(**kwargs)
