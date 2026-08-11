from __future__ import annotations

import io
import json
from email.message import Message

import pytest

from plugins.backup.backup_config import BackupAction, BackupTarget
from plugins.backup.home_assistant_backup_client import (
    HomeAssistantBackupClient,
    HomeAssistantBackupError,
)


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, *, content_length: int | None = None) -> None:
        super().__init__(body)
        self.headers = Message()
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)


def make_target() -> BackupTarget:
    return BackupTarget(
        id="ha-01",
        label="HA-01",
        url="http://ha-01:8123",
        token_environment_variable="HA_TOKEN",
        password_environment_variable="HA_PASSWORD",
        schedule="0 2 * * *",
    )


def test_home_assistant_client_uses_supervisor_proxy_for_full_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []

    def fake_urlopen(request, **kwargs):
        del kwargs
        requests.append(request)
        return FakeResponse(
            json.dumps({"result": "ok", "data": {"slug": "abc123"}}).encode()
        )

    monkeypatch.setattr(
        "plugins.backup.home_assistant_backup_client.urlopen",
        fake_urlopen,
    )
    client = HomeAssistantBackupClient(make_target(), "secret")

    backup = client.create_full_backup(
        "Ohana-ha-01-date",
        password="backup-password",
    )

    assert backup.slug == "abc123"
    assert requests[0].full_url == ("http://ha-01:8123/api/hassio/backups/new/full")
    assert requests[0].headers["Authorization"] == "Bearer secret"
    assert json.loads(requests[0].data) == {
        "name": "Ohana-ha-01-date",
        "password": "backup-password",
        "background": False,
    }


def test_home_assistant_client_requires_content_length_for_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "plugins.backup.home_assistant_backup_client.urlopen",
        lambda *args, **kwargs: FakeResponse(b"archive"),
    )
    client = HomeAssistantBackupClient(make_target(), "secret")

    with pytest.raises(HomeAssistantBackupError, match="unbounded upload"):
        with client.download("slug"):
            pass


def test_home_assistant_client_exposes_exact_download_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "plugins.backup.home_assistant_backup_client.urlopen",
        lambda *args, **kwargs: FakeResponse(b"archive", content_length=7),
    )
    client = HomeAssistantBackupClient(make_target(), "secret")

    with client.download("slug") as download:
        assert download.size_bytes == 7
        assert download.stream.read() == b"archive"


def test_home_assistant_client_accepts_state_list_from_pre_backup_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target()
    target = BackupTarget(
        id=target.id,
        label=target.label,
        url=target.url,
        token_environment_variable=target.token_environment_variable,
        password_environment_variable=target.password_environment_variable,
        schedule=target.schedule,
        pre_backup_action=BackupAction(
            domain="script",
            service="ohana_backup_zwave_nvm",
        ),
    )
    monkeypatch.setattr(
        "plugins.backup.home_assistant_backup_client.urlopen",
        lambda *args, **kwargs: FakeResponse(b"[]"),
    )

    HomeAssistantBackupClient(target, "secret").run_pre_backup_action()
