from __future__ import annotations

import hashlib
import io
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from plugins.backup.backup_config import BackupConfig, BackupTarget
from plugins.backup.backup_coordinator import (
    BackupCoordinator,
    BackupExecutionError,
)
from plugins.backup.home_assistant_backup_client import HomeAssistantBackup
from plugins.backup.rclone_uploader import UploadReceipt


class FakeBackupClient:
    def __init__(self) -> None:
        self.backups = (
            HomeAssistantBackup("old-managed", "Ohana-ha-01-20260810T020000Z"),
            HomeAssistantBackup("manual", "Before upgrade"),
        )
        self.deleted: list[str] = []
        self.prepared = False

    def list_backups(self) -> tuple[HomeAssistantBackup, ...]:
        return self.backups

    def run_pre_backup_action(self) -> None:
        self.prepared = True

    def create_full_backup(self, name: str, *, password: str) -> HomeAssistantBackup:
        assert password == "backup-password"
        return HomeAssistantBackup("new/slug", name)

    @contextmanager
    def download(self, slug: str):
        assert slug == "new/slug"
        body = b"encrypted-haos-backup"
        yield SimpleNamespace(stream=io.BytesIO(body), size_bytes=len(body))

    def delete(self, slug: str) -> None:
        self.deleted.append(slug)


class FakeUploader:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.uploads: list[tuple[str, bytes]] = []

    def upload(self, stream, *, size_bytes: int, remote_path: str) -> UploadReceipt:
        if self.fail:
            raise RuntimeError("iCloud unavailable")
        body = stream.read()
        assert len(body) == size_bytes
        self.uploads.append((remote_path, body))
        return UploadReceipt(
            remote_path=remote_path,
            size_bytes=size_bytes,
            sha256=hashlib.sha256(body).hexdigest(),
        )

    def check_remote(self) -> None:
        if self.fail:
            raise RuntimeError("iCloud unavailable")


def make_target() -> BackupTarget:
    return BackupTarget(
        id="ha-01",
        label="HA-01",
        url="http://ha-01:8123",
        token_environment_variable="OHANA_TEST_BACKUP_TOKEN",
        password_environment_variable="OHANA_TEST_BACKUP_PASSWORD",
        schedule="0 2 * * *",
    )


def test_coordinator_streams_checksum_then_keeps_only_new_managed_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OHANA_TEST_BACKUP_TOKEN", "secret")
    monkeypatch.setenv("OHANA_TEST_BACKUP_PASSWORD", "backup-password")
    client = FakeBackupClient()
    uploader = FakeUploader()
    coordinator = BackupCoordinator(
        BackupConfig(targets=(make_target(),)),
        client_factory=lambda target, token: client,
        uploader=uploader,
    )

    result = coordinator.run(
        make_target(),
        now=datetime(2026, 8, 11, 2, 0, tzinfo=UTC),
    )

    assert client.prepared is True
    assert client.deleted == ["old-managed"]
    assert result.deleted_local_backups == 1
    assert result.remote_path == (
        "icloud:Ohana/Backups/ha-01/2026/08/20260811T020000Z_new_slug.tar"
    )
    assert len(uploader.uploads) == 2
    checksum_path, checksum_body = uploader.uploads[1]
    assert checksum_path == f"{result.remote_path}.sha256"
    assert checksum_body.decode().endswith("  20260811T020000Z_new_slug.tar\n")


def test_coordinator_never_rotates_local_backup_when_upload_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OHANA_TEST_BACKUP_TOKEN", "secret")
    monkeypatch.setenv("OHANA_TEST_BACKUP_PASSWORD", "backup-password")
    client = FakeBackupClient()
    coordinator = BackupCoordinator(
        BackupConfig(targets=(make_target(),)),
        client_factory=lambda target, token: client,
        uploader=FakeUploader(fail=True),
    )

    with pytest.raises(BackupExecutionError, match="iCloud unavailable") as error:
        coordinator.run(make_target())

    assert error.value.stage == "upload"
    assert client.deleted == []


def test_coordinator_requires_token_before_contacting_home_assistant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OHANA_TEST_BACKUP_TOKEN", raising=False)
    monkeypatch.delenv("OHANA_TEST_BACKUP_PASSWORD", raising=False)
    coordinator = BackupCoordinator(BackupConfig(targets=(make_target(),)))

    with pytest.raises(BackupExecutionError, match="OHANA_TEST_BACKUP_TOKEN") as error:
        coordinator.run(make_target())

    assert error.value.stage == "authentication"


def test_coordinator_requires_explicit_backup_encryption_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OHANA_TEST_BACKUP_TOKEN", "secret")
    monkeypatch.delenv("OHANA_TEST_BACKUP_PASSWORD", raising=False)
    coordinator = BackupCoordinator(BackupConfig(targets=(make_target(),)))

    with pytest.raises(
        BackupExecutionError,
        match="OHANA_TEST_BACKUP_PASSWORD",
    ) as error:
        coordinator.run(make_target())

    assert error.value.stage == "encryption"


def test_preflight_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OHANA_TEST_BACKUP_TOKEN", "secret")
    monkeypatch.setenv("OHANA_TEST_BACKUP_PASSWORD", "backup-password")
    client = FakeBackupClient()
    coordinator = BackupCoordinator(
        BackupConfig(targets=(make_target(),)),
        client_factory=lambda target, token: client,
        uploader=FakeUploader(),
    )

    backup_count = coordinator.preflight(make_target())

    assert backup_count == 2
    assert client.prepared is False
    assert client.deleted == []


def test_coordinator_reads_secrets_from_environment_file(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OHANA_TEST_BACKUP_TOKEN", raising=False)
    monkeypatch.delenv("OHANA_TEST_BACKUP_PASSWORD", raising=False)
    environment_file = tmp_path / "backup.env"
    environment_file.write_text(
        "OHANA_TEST_BACKUP_TOKEN=secret\n"
        'OHANA_TEST_BACKUP_PASSWORD="backup-password"\n',
        encoding="utf-8",
    )
    client = FakeBackupClient()
    coordinator = BackupCoordinator(
        BackupConfig(
            targets=(make_target(),),
            environment_file=str(environment_file),
        ),
        client_factory=lambda target, token: client,
        uploader=FakeUploader(),
    )

    assert coordinator.preflight(make_target()) == 2
