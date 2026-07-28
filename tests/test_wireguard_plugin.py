"""Tests for the Freebox WireGuard observation plugin."""

import pytest

from plugins.wireguard.wireguard_config import WireGuardConfig
from plugins.wireguard.wireguard_plugin import WireGuardPlugin
from plugins.wireguard.wireguard_result import WireGuardCheckResult


class FakeWireGuardCheck:
    def __init__(self, result: WireGuardCheckResult) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []

    def check(
        self,
        service_name: str,
        base_url: str,
        *,
        server_name: str,
        app_id: str,
        app_version: str,
        app_token: str | None,
        timeout: float,
        retries: int,
        verify_tls: bool,
    ) -> WireGuardCheckResult:
        self.calls.append(
            (
                service_name,
                base_url,
                server_name,
                app_id,
                app_version,
                app_token,
                timeout,
                retries,
                verify_tls,
            )
        )
        return self.result


def test_wireguard_plugin_returns_observer_result() -> None:
    check = FakeWireGuardCheck(
        WireGuardCheckResult(
            service_name="freebox-wireguard",
            base_url="http://192.168.1.1",
            server_name="wireguard",
            healthy=True,
            state="started",
            connection_count=1,
        )
    )
    plugin = WireGuardPlugin(
        check=check,
        config=WireGuardConfig(
            timeout=2.0,
            retries=1,
            app_token="secret",
        ),
    )

    result = plugin.execute(
        service_id="freebox-wireguard",
        base_url="http://192.168.1.1",
        server_name="wireguard",
    )

    assert result.success is True
    assert result.check == "wireguard.status"
    assert result.metadata["state"] == "started"
    assert result.metadata["connection_count"] == 1
    assert check.calls == [
        (
            "freebox-wireguard",
            "http://192.168.1.1",
            "wireguard",
            "fr.ohana.agent",
            "1.7.1",
            "secret",
            2.0,
            1,
            False,
        )
    ]


def test_wireguard_plugin_requires_freebox_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        WireGuardPlugin().execute(
            service_id="freebox-wireguard",
            base_url="",
        )
