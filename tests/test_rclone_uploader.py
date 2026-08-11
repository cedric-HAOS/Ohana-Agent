from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.backup.backup_config import BackupConfig
from plugins.backup.rclone_uploader import RcloneStreamUploader, RcloneUploadError


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

    monkeypatch.setattr("plugins.backup.rclone_uploader.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "plugins.backup.rclone_uploader.subprocess.run",
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

    monkeypatch.setattr("plugins.backup.rclone_uploader.subprocess.run", fake_run)
    uploader = RcloneStreamUploader(BackupConfig(rclone_remote="icloud:Ohana/Backups"))

    uploader.check_remote()

    assert commands[0][0:3] == ["/usr/bin/rclone", "lsd", "icloud:"]
