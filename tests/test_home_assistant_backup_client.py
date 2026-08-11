from __future__ import annotations

import io
from email.message import Message

import pytest

from plugins.backup.backup_config import BackupAction, BackupTarget
from plugins.backup.home_assistant_backup_client import (
    HomeAssistantBackup,
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


class FakeWebSocket:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = iter(messages)
        self.sent: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def receive_json(self):
        return next(self.messages)

    async def send_json(self, payload):
        self.sent.append(payload)


class FakeSession:
    def __init__(self, websocket: FakeWebSocket) -> None:
        self.websocket = websocket

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def ws_connect(self, *args, **kwargs):
        return self.websocket


def test_home_assistant_client_uses_public_websocket_api_for_full_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = FakeWebSocket(
        [
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "result", "success": True, "result": None},
            {
                "id": 2,
                "type": "result",
                "success": True,
                "result": {"agents": [{"agent_id": "hassio.local"}]},
            },
            {
                "id": 3,
                "type": "result",
                "success": True,
                "result": {"backup_job_id": "job"},
            },
            {
                "id": 1,
                "type": "event",
                "event": {"manager_state": "create_backup", "state": "completed"},
            },
            {
                "id": 4,
                "type": "result",
                "success": True,
                "result": {
                    "backups": [
                        {
                            "backup_id": "abc123",
                            "name": "Ohana-ha-01-date",
                            "agents": {"hassio.local": {}},
                        }
                    ]
                },
            },
        ]
    )
    client = HomeAssistantBackupClient(make_target(), "secret")
    monkeypatch.setattr(client, "_session", lambda: FakeSession(websocket))

    backup = client.create_full_backup(
        "Ohana-ha-01-date",
        password="backup-password",
    )

    assert backup.slug == "abc123"
    assert backup.agent_id == "hassio.local"
    assert websocket.sent[1] == {"id": 1, "type": "backup/subscribe_events"}
    generate = websocket.sent[3]
    assert generate["type"] == "backup/generate"
    assert generate["agent_ids"] == ["hassio.local"]
    assert generate["password"] == "backup-password"
    assert generate["include_all_addons"] is True


def test_home_assistant_client_requires_a_known_size_for_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "plugins.backup.home_assistant_backup_client.urlopen",
        lambda *args, **kwargs: FakeResponse(b"archive"),
    )
    client = HomeAssistantBackupClient(make_target(), "secret")
    monkeypatch.setattr(
        client,
        "_backup",
        lambda slug: HomeAssistantBackup(slug=slug),
    )

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
    monkeypatch.setattr(
        client,
        "_backup",
        lambda slug: HomeAssistantBackup(slug=slug),
    )

    with client.download("slug") as download:
        assert download.size_bytes == 7
        assert download.stream.read() == b"archive"


def test_home_assistant_client_uses_inventory_size_for_chunked_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "plugins.backup.home_assistant_backup_client.urlopen",
        lambda *args, **kwargs: FakeResponse(b"archive"),
    )
    client = HomeAssistantBackupClient(make_target(), "secret")
    monkeypatch.setattr(
        client,
        "_backup",
        lambda slug: HomeAssistantBackup(slug=slug, size_bytes=7),
    )

    with client.download("slug") as download:
        assert download.size_bytes == 7
        assert download.stream.read() == b"archive"


def test_home_assistant_client_reads_exact_size_from_backup_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = {
        "backups": [
            {
                "backup_id": "slug",
                "name": "Ohana-linky-01-date",
                "agents": {
                    "hassio.local": {
                        "protected": True,
                        "size": 7,
                    }
                },
            }
        ]
    }
    client = HomeAssistantBackupClient(make_target(), "secret")
    monkeypatch.setattr(client, "_command", lambda *args, **kwargs: object())
    monkeypatch.setattr(client, "_run", lambda _awaitable: inventory)

    backups = client.list_backups()

    assert backups == (
        HomeAssistantBackup(
            slug="slug",
            name="Ohana-linky-01-date",
            agent_id="hassio.local",
            size_bytes=7,
        ),
    )


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
