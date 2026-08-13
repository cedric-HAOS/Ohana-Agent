from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from plugins.backup.backup_config import BackupConfig, InfraBackupConfig
from plugins.backup.infra_backup_coordinator import InfraBackupCoordinator
from plugins.backup.rclone_uploader import RcloneStreamUploader, UploadReceipt


class NonClosingBytesIO(io.BytesIO):
    def close(self) -> None:
        pass


class FakeAgeProcess:
    def __init__(self, command) -> None:
        self.command = tuple(command)
        self.stdin = NonClosingBytesIO()
        self.returncode = 0

    def communicate(self):
        destination = Path(self.command[self.command.index("--output") + 1])
        destination.write_bytes(b"age-encrypted")
        return b"", b""

    def kill(self) -> None:
        self.returncode = -9


class FakeUploader:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes]] = []
        self.prunes: list[tuple[str, int, str | None]] = []

    def upload(self, stream, *, size_bytes: int, remote_path: str) -> UploadReceipt:
        body = stream.read()
        assert len(body) == size_bytes
        self.uploads.append((remote_path, body))
        return UploadReceipt(
            remote_path=remote_path,
            size_bytes=size_bytes,
            sha256=hashlib.sha256(body).hexdigest(),
        )

    def check_remote(self) -> None:
        pass

    def prune_complete_backup_directories(
        self,
        remote_root: str,
        *,
        keep_count: int,
        protected_directory: str | None = None,
    ) -> int:
        self.prunes.append((remote_root, keep_count, protected_directory))
        return 2 if keep_count else 0


def test_infra_backup_publishes_manifest_after_encrypted_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = tmp_path / "etc" / "ohana-agent"
    vision = tmp_path / "etc" / "ohana-vision"
    dnsmasq = tmp_path / "etc" / "dnsmasq.d"
    chrony = tmp_path / "etc" / "chrony.conf"
    for directory in (agent, vision, dnsmasq):
        directory.mkdir(parents=True)
        (directory / "config.yaml").write_text("enabled: true\n", encoding="utf-8")
    chrony.write_text("pool example.test\n", encoding="utf-8")
    age = tmp_path / "age"
    age.touch()
    uploader = FakeUploader()
    monkeypatch.setattr(RcloneStreamUploader, "_require_tmpfs", lambda _path: None)
    coordinator = InfraBackupCoordinator(
        BackupConfig(
            rclone_remote="icloud:Ohana/Backups",
            temporary_directory=str(tmp_path / "runtime"),
            infra_01=InfraBackupConfig(
                enabled=True,
                age_binary=str(age),
                age_recipient="age1recipient",
                remote_retention_count=3,
            ),
        ),
        uploader=uploader,
        sources=(agent, vision, dnsmasq, chrony),
        vision_database=tmp_path / "missing.db",
        version_resolver=lambda distribution: {
            "ohana-agent": "1.12.7",
            "ohana-vision": "1.11.8",
        }[distribution],
        popen_factory=lambda command, **_kwargs: FakeAgeProcess(command),
    )

    result = coordinator.run(now=datetime(2026, 8, 13, 12, tzinfo=UTC))

    assert result.backup_id == "20260813T120000Z"
    assert result.deleted_remote_backups == 2
    assert len(uploader.uploads) == 2
    archive_path, archive_body = uploader.uploads[0]
    manifest_path, manifest_body = uploader.uploads[1]
    assert archive_path.endswith("/20260813T120000Z/20260813T120000Z.tar.age")
    assert archive_body == b"age-encrypted"
    assert manifest_path.endswith("/20260813T120000Z/manifest.json")
    manifest = json.loads(manifest_body)
    assert manifest["platform_version"] is None
    assert manifest["agent_version"] == "1.12.7"
    assert manifest["archive"]["sha256"] == hashlib.sha256(archive_body).hexdigest()
    assert uploader.prunes == [("icloud:Ohana/Backups/infra-01", 3, "20260813T120000Z")]
