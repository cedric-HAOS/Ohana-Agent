"""Tests for the installed Freebox authorization command."""

from pathlib import Path

import yaml

from plugins.wireguard import authorize_freebox as authorization


class FakeFreeboxClient:
    """Return deterministic Freebox authorization responses."""

    def __init__(self, statuses: list[str]) -> None:
        self.statuses = iter(statuses)
        self.request: dict[str, object] | None = None

    def request_authorization(
        self,
        base_url: str,
        *,
        app_id: str,
        app_name: str,
        app_version: str,
        device_name: str,
        verify_tls: bool,
    ) -> tuple[str, int, str]:
        self.request = {
            "base_url": base_url,
            "app_id": app_id,
            "app_name": app_name,
            "app_version": app_version,
            "device_name": device_name,
            "verify_tls": verify_tls,
        }
        return "secret-token", 42, "http://192.168.1.1/api/v15/"

    def authorization_status(
        self,
        api_root: str,
        track_id: int,
        *,
        verify_tls: bool,
    ) -> str:
        assert api_root == "http://192.168.1.1/api/v15/"
        assert track_id == 42
        assert verify_tls is False
        return next(self.statuses)


def write_config(path: Path) -> None:
    """Write a minimal WireGuard plugin configuration."""
    path.write_text(
        "\n".join(
            (
                "enabled: true",
                "app_id: fr.ohana.agent",
                "app_version: 1.7.3",
                "app_token: null",
                "verify_tls: false",
                "",
            )
        ),
        encoding="utf-8",
    )


def test_parse_arguments_uses_installed_configuration_path() -> None:
    arguments = authorization.parse_arguments([])

    assert arguments.url == "http://mafreebox.freebox.fr"
    assert arguments.config == Path("/etc/ohana-agent/plugins/wireguard.yaml")
    assert arguments.timeout == 90.0


def test_authorize_freebox_stores_granted_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "wireguard.yaml"
    write_config(config_path)
    client = FakeFreeboxClient(["pending", "granted"])
    monkeypatch.setattr(authorization.time, "sleep", lambda _seconds: None)

    exit_code = authorization.authorize_freebox(
        base_url="http://192.168.1.1",
        config_path=config_path,
        approval_timeout=90.0,
        client=client,
    )

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["app_token"] == "secret-token"
    assert client.request is not None
    assert client.request["base_url"] == "http://192.168.1.1"
    assert client.request["app_version"] == "1.7.3"


def test_authorize_freebox_does_not_store_denied_token(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "wireguard.yaml"
    write_config(config_path)
    client = FakeFreeboxClient(["denied"])

    exit_code = authorization.authorize_freebox(
        base_url="http://192.168.1.1",
        config_path=config_path,
        approval_timeout=90.0,
        client=client,
    )

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["app_token"] is None
