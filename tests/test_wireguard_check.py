"""Tests for Freebox WireGuard server checks."""

from plugins.wireguard.wireguard_check import WireGuardCheck
from plugins.wireguard.wireguard_client import FreeboxWireGuardResponse


class FakeFreeboxWireGuardClient:
    def __init__(self, results: list[FreeboxWireGuardResponse]) -> None:
        self.results = results
        self.calls: list[tuple[object, ...]] = []

    def query(
        self,
        base_url: str,
        *,
        app_id: str,
        app_version: str,
        app_token: str | None,
        server_name: str,
        timeout: float,
        verify_tls: bool,
    ) -> FreeboxWireGuardResponse:
        self.calls.append(
            (
                base_url,
                app_id,
                app_version,
                app_token,
                server_name,
                timeout,
                verify_tls,
            )
        )
        return self.results[len(self.calls) - 1]


def test_wireguard_check_accepts_started_freebox_server() -> None:
    client = FakeFreeboxWireGuardClient(
        [
            FreeboxWireGuardResponse(
                success=True,
                state="started",
                connection_count=2,
            )
        ]
    )

    result = WireGuardCheck(client=client).check(
        "freebox-wireguard",
        "http://192.168.1.1",
        app_id="fr.ohana.agent",
        app_version="1.7.2",
        app_token="secret",
    )

    assert result.healthy is True
    assert result.state == "started"
    assert result.connection_count == 2
    assert result.attempts == 1


def test_wireguard_check_retries_transient_freebox_failure() -> None:
    client = FakeFreeboxWireGuardClient(
        [
            FreeboxWireGuardResponse(success=False, error="temporary failure"),
            FreeboxWireGuardResponse(success=True, state="started"),
        ]
    )

    result = WireGuardCheck(client=client).check(
        "freebox-wireguard",
        "http://192.168.1.1",
        app_id="fr.ohana.agent",
        app_version="1.7.2",
        app_token="secret",
        retries=1,
    )

    assert result.healthy is True
    assert result.attempts == 2
