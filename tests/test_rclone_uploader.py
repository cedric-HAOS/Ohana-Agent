from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ohana_agent.plugins.backup.config import BackupConfig
from ohana_agent.plugins.backup.rclone_uploader import (
    RcloneStreamUploader,
    RcloneUploadError,
)


class InputSink:
    def __init__(self) -> None:
        self.body = bytearray()

    def write(self, data: bytes) -> int:
        self.body.extend(data)
        return len(data)

    def close(self) -> None:
        pass


class FakeProcess:
    def __init__(self, command: list[str], **kwargs: object) -> None:
        del kwargs
        self.command = command
        self.input_sink = InputSink()
        self.stdin = self.input_sink
        self.stderr = io.BytesIO()
        self.killed = False
        self.returncode = 0

    def communicate(self):
        return None, self.stderr.getvalue()

    def kill(self) -> None:
        self.killed = True


def test_rclone_uploader_streams_exact_size_and_validates_remote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes: list[FakeProcess] = []

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        process = FakeProcess(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(
        "ohana_agent.plugins.backup.rclone_uploader.subprocess.Popen", fake_popen
    )
    monkeypatch.setattr(
        "ohana_agent.plugins.backup.rclone_uploader.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"Size": 6}),
            stderr="",
        ),
    )
    uploader = RcloneStreamUploader(
        BackupConfig(
            temporary_directory=str(tmp_path),
            require_tmpfs=False,
            chunk_size_bytes=2,
        )
    )

    receipt = uploader.upload(
        io.BytesIO(b"backup"),
        size_bytes=6,
        remote_path="icloud:Ohana/archive.tar",
    )

    assert bytes(processes[0].input_sink.body) == b"backup"
    assert "--size" in processes[0].command
    assert processes[0].command[processes[0].command.index("--size") + 1] == "6"
    assert receipt.size_bytes == 6


def test_rclone_uploader_refuses_non_tmpfs_path(
    tmp_path: Path,
) -> None:
    uploader = RcloneStreamUploader(
        BackupConfig(temporary_directory=str(tmp_path), require_tmpfs=True)
    )

    with pytest.raises(RcloneUploadError, match="not tmpfs|Cannot verify"):
        uploader.upload(
            io.BytesIO(b"backup"),
            size_bytes=6,
            remote_path="icloud:Ohana/archive.tar",
        )


def test_rclone_remote_check_uses_remote_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "ohana_agent.plugins.backup.rclone_uploader.subprocess.run", fake_run
    )
    uploader = RcloneStreamUploader(BackupConfig(rclone_remote="icloud:Ohana/Backups"))

    uploader.check_remote()

    assert commands[0][0:3] == ["/usr/bin/rclone", "lsd", "icloud:"]


def test_remote_rotation_deletes_only_old_complete_backups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    ids = ("20260810T010000Z", "20260811T010000Z", "20260812T010000Z")

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        commands.append(command)
        operation = command[1]
        if operation == "lsf":
            return SimpleNamespace(
                returncode=0,
                stdout="\n".join(f"{backup_id}/" for backup_id in ids),
                stderr="",
            )
        if operation == "lsjson":
            backup_id = command[2].split("/")[-2]
            if backup_id == ids[1]:
                return SimpleNamespace(returncode=1, stdout="", stderr="missing")
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"IsDir": False, "Size": 500}),
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "ohana_agent.plugins.backup.rclone_uploader.subprocess.run", fake_run
    )
    uploader = RcloneStreamUploader(BackupConfig())

    deleted = uploader.prune_complete_backup_directories(
        "icloud:Ohana/Backups/infra-01",
        keep_count=1,
    )

    assert deleted == 1
    purge_commands = [command for command in commands if command[1] == "purge"]
    assert len(purge_commands) == 1
    assert ids[0] in purge_commands[0][2]
    assert all(ids[1] not in command[2] for command in purge_commands)


def _haos_listing(monkeypatch, files, *, fail_delete=False):
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        commands.append(command)
        if command[1] == "lsf":
            return SimpleNamespace(returncode=0, stdout="\n".join(files), stderr="")
        if command[1] == "deletefile" and fail_delete:
            return SimpleNamespace(returncode=1, stdout="", stderr="denied")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "ohana_agent.plugins.backup.rclone_uploader.subprocess.run", fake_run
    )
    return commands


HAOS_FILES = [
    "2026/09/20260920T000000Z_aaa.tar",
    "2026/09/20260920T000000Z_aaa.tar.sha256",
    "2026/10/20261004T000000Z_bbb.tar",
    "2026/10/20261004T000000Z_bbb.tar.sha256",
    "2026/10/20261011T000000Z_ccc.tar",
    "2026/10/20261011T000000Z_ccc.tar.sha256",
    "2026/10/20261018T000000Z_ddd.tar",
]


def test_haos_rotation_keeps_the_newest_complete_archives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = _haos_listing(monkeypatch, HAOS_FILES)
    uploader = RcloneStreamUploader(BackupConfig())

    deleted = uploader.prune_complete_archives(
        "icloud:Ohana/Backups/ha-01", keep_count=2
    )

    # ddd has no checksum yet: incomplete, neither counted nor deleted.
    assert deleted == 1
    removed = [command[2] for command in commands if command[1] == "deletefile"]
    assert removed == [
        "icloud:Ohana/Backups/ha-01/2026/09/20260920T000000Z_aaa.tar",
        "icloud:Ohana/Backups/ha-01/2026/09/20260920T000000Z_aaa.tar.sha256",
    ]


def test_haos_rotation_never_deletes_the_archive_just_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = _haos_listing(monkeypatch, HAOS_FILES)
    uploader = RcloneStreamUploader(BackupConfig())

    deleted = uploader.prune_complete_archives(
        "icloud:Ohana/Backups/ha-01",
        keep_count=1,
        protected_path="icloud:Ohana/Backups/ha-01/2026/09/20260920T000000Z_aaa.tar",
    )

    assert deleted == 1
    removed = " ".join(c[2] for c in commands if c[1] == "deletefile")
    assert "aaa" not in removed and "bbb" in removed and "ccc" not in removed


def test_haos_rotation_zero_keeps_everything_without_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = _haos_listing(monkeypatch, HAOS_FILES)

    assert (
        RcloneStreamUploader(BackupConfig()).prune_complete_archives(
            "icloud:Ohana/Backups/ha-01", keep_count=0
        )
        == 0
    )
    assert commands == []


def test_haos_rotation_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _haos_listing(monkeypatch, HAOS_FILES, fail_delete=True)

    with pytest.raises(RcloneUploadError, match="could not delete"):
        RcloneStreamUploader(BackupConfig()).prune_complete_archives(
            "icloud:Ohana/Backups/ha-01", keep_count=1
        )
