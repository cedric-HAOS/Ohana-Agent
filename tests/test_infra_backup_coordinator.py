from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.backup.backup_config import BackupConfig, InfraBackupConfig
from plugins.backup.backup_coordinator import BackupExecutionError
from plugins.backup.infra_backup_coordinator import InfraBackupCoordinator
from plugins.backup.rclone_uploader import RcloneStreamUploader, UploadReceipt


class NonClosingBytesIO(io.BytesIO):
    def close(self) -> None:
        pass


class FakeAgeProcess:
    def __init__(self, command) -> None:
        self.command = tuple(command)
        self.stdin = NonClosingBytesIO()
        self.input = self.stdin
        self.returncode = 0

    def communicate(self):
        destination = Path(self.command[self.command.index("--output") + 1])
        destination.write_bytes(b"age-encrypted")
        return b"", b""

    def kill(self) -> None:
        self.returncode = -9

    def poll(self):
        return self.returncode


class BrokenAgeInput(NonClosingBytesIO):
    def write(self, _body) -> int:
        raise BrokenPipeError(32, "Broken pipe")


class FailingAgeProcess(FakeAgeProcess):
    def __init__(self, command) -> None:
        super().__init__(command)
        self.stdin = BrokenAgeInput()
        self.returncode = 1

    def communicate(self):
        return b"", b"age: failed to close output: no space left on device"


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


class FakeVersionResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def test_infra_backup_reads_vision_version_from_local_api() -> None:
    requests: list[tuple[str, float]] = []

    def reader(url: str, *, timeout: float):
        requests.append((url, timeout))
        return FakeVersionResponse(b'{"name":"Ohana-Vision","version":"1.13.0"}')

    coordinator = InfraBackupCoordinator(
        BackupConfig(),
        vision_version_reader=reader,
    )

    assert coordinator._installed_version("ohana-vision") == "1.13.0"
    assert requests == [
        ("http://127.0.0.1:8000/api/version", 5.0),
    ]


@pytest.mark.parametrize(
    "body",
    (
        b"invalid",
        b'{"name":"Ohana-Vision","version":""}',
        b"[]",
    ),
)
def test_infra_backup_rejects_unavailable_vision_version(body: bytes) -> None:
    coordinator = InfraBackupCoordinator(
        BackupConfig(),
        vision_version_reader=lambda url, **kwargs: FakeVersionResponse(body),
    )

    with pytest.raises(
        BackupExecutionError,
        match="Installed version unavailable for ohana-vision",
    ):
        coordinator._installed_version("ohana-vision")


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
    identity = tmp_path / "infra-01.agekey"
    identity.write_bytes(b"AGE-SECRET-KEY-1TEST\n")
    uploader = FakeUploader()
    monkeypatch.setattr(RcloneStreamUploader, "_require_tmpfs", lambda _path: None)
    age_processes: list[FakeAgeProcess] = []

    def create_age_process(command, **_kwargs):
        process = FakeAgeProcess(command)
        age_processes.append(process)
        return process

    coordinator = InfraBackupCoordinator(
        BackupConfig(
            rclone_remote="icloud:Ohana/Backups",
            temporary_directory=str(tmp_path / "runtime"),
            infra_01=InfraBackupConfig(
                enabled=True,
                age_binary=str(age),
                age_recipient="age1recipient",
                age_identity_file=str(identity),
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
        popen_factory=create_age_process,
    )

    result = coordinator.run(now=datetime(2026, 8, 13, 12, tzinfo=UTC))

    assert result.backup_id == "20260813T120000Z"
    assert result.deleted_remote_backups == 2
    assert len(uploader.uploads) == 3
    recovery_path, recovery_body = uploader.uploads[0]
    archive_path, archive_body = uploader.uploads[1]
    manifest_path, manifest_body = uploader.uploads[2]
    assert recovery_path == "icloud:Ohana/Recovery/infra-01.agekey"
    assert recovery_body == b"AGE-SECRET-KEY-1TEST\n"
    assert archive_path.endswith("/20260813T120000Z/20260813T120000Z.tar.age")
    assert archive_body == b"age-encrypted"
    assert manifest_path.endswith("/20260813T120000Z/manifest.json")
    manifest = json.loads(manifest_body)
    assert manifest["platform_version"] is None
    assert manifest["agent_version"] == "1.12.7"
    assert manifest["archive"]["sha256"] == hashlib.sha256(archive_body).hexdigest()
    assert uploader.prunes == [("icloud:Ohana/Backups/infra-01", 3, "20260813T120000Z")]
    assert age_processes[0].input.getvalue().startswith(b"\x1f\x8b")


def test_infra_backup_reports_age_error_instead_of_broken_pipe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "etc" / "ohana-agent"
    source.mkdir(parents=True)
    (source / "config.yaml").write_text("enabled: true\n", encoding="utf-8")
    destination = tmp_path / "backup.tar.age"
    descriptor = tmp_path / "descriptor.json"
    descriptor.write_text("{}\n", encoding="utf-8")
    coordinator = InfraBackupCoordinator(
        BackupConfig(
            infra_01=InfraBackupConfig(
                enabled=True,
                age_binary=str(tmp_path / "age"),
            )
        ),
        sources=(source,),
        popen_factory=lambda command, **_kwargs: FailingAgeProcess(command),
    )

    with pytest.raises(BackupExecutionError, match="no space left on device"):
        coordinator._create_encrypted_archive(
            destination,
            snapshot=tmp_path / "missing.db",
            descriptor=descriptor,
            recipient="age1recipient",
        )


def test_infra_backup_rejects_tmpfs_too_small_for_vision_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "vision.db"
    database.write_bytes(b"database")
    coordinator = InfraBackupCoordinator(
        BackupConfig(),
        vision_database=database,
    )
    monkeypatch.setattr(
        "plugins.backup.infra_backup_coordinator.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=database.stat().st_size),
    )

    with pytest.raises(BackupExecutionError, match="Insufficient tmpfs space"):
        coordinator._ensure_temporary_capacity(tmp_path)
