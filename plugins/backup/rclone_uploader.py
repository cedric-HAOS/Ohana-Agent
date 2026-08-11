"""Bounded-memory rclone streaming uploader."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from plugins.backup.backup_config import BackupConfig


class RcloneUploadError(RuntimeError):
    """Raised when rclone cannot upload or validate an object."""


@dataclass(frozen=True, slots=True)
class UploadReceipt:
    """Validated remote upload details."""

    remote_path: str
    size_bytes: int
    sha256: str


class RcloneStreamUploader:
    """Upload streams with an explicit size and a RAM-backed temp directory."""

    def __init__(self, config: BackupConfig) -> None:
        self._config = config

    def upload(
        self,
        stream: BinaryIO,
        *,
        size_bytes: int,
        remote_path: str,
    ) -> UploadReceipt:
        if size_bytes <= 0:
            raise ValueError("size_bytes must be greater than zero.")

        temporary_directory = Path(self._config.temporary_directory)
        if self._config.require_tmpfs:
            self._require_tmpfs(temporary_directory)
        temporary_directory.mkdir(parents=True, exist_ok=True)
        command = self._base_command("rcat", remote_path)
        command.extend(["--size", str(size_bytes), "--log-level", "ERROR"])
        environment = os.environ.copy()
        environment["TMPDIR"] = str(temporary_directory)

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=environment,
        )
        if process.stdin is None:
            process.kill()
            raise RcloneUploadError("rclone did not expose its input stream.")

        digest = hashlib.sha256()
        transferred = 0
        try:
            while True:
                chunk = stream.read(self._config.chunk_size_bytes)
                if not chunk:
                    break
                process.stdin.write(chunk)
                digest.update(chunk)
                transferred += len(chunk)
            process.stdin.close()
            process.stdin = None
            _stdout, stderr_bytes = process.communicate()
            return_code = process.returncode
        except Exception:
            process.kill()
            process.communicate()
            raise

        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
        if return_code != 0:
            raise RcloneUploadError(
                f"rclone upload failed with exit code {return_code}: {stderr[:1000]}"
            )
        if transferred != size_bytes:
            raise RcloneUploadError(
                f"Backup stream size mismatch: expected {size_bytes}, "
                f"got {transferred}."
            )

        self._validate_remote_size(remote_path, size_bytes)
        return UploadReceipt(
            remote_path=remote_path,
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
        )

    def check_remote(self) -> None:
        """Validate the configured rclone binary, configuration and remote."""
        remote_name = self._config.rclone_remote.partition(":")[0]
        result = subprocess.run(
            self._base_command("lsd", f"{remote_name}:")
            + ["--max-depth", "1", "--log-level", "ERROR"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RcloneUploadError(
                f"rclone could not access the configured remote: {result.stderr[:1000]}"
            )

    def _validate_remote_size(self, remote_path: str, expected_size: int) -> None:
        result = subprocess.run(
            self._base_command("lsjson", remote_path) + ["--stat"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RcloneUploadError(
                f"rclone could not validate the remote object: {result.stderr[:1000]}"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RcloneUploadError(
                "rclone returned invalid validation JSON."
            ) from error
        if not isinstance(payload, dict) or payload.get("Size") != expected_size:
            raise RcloneUploadError(
                "Remote object size does not match the streamed backup size."
            )

    def _base_command(self, operation: str, remote_path: str) -> list[str]:
        return [
            self._config.rclone_binary,
            operation,
            remote_path,
            "--config",
            self._config.rclone_config_path,
            "--temp-dir",
            self._config.temporary_directory,
        ]

    @staticmethod
    def _require_tmpfs(path: Path) -> None:
        """Refuse fallback storage unless the configured path belongs to tmpfs."""
        mounts_path = Path("/proc/mounts")
        if not mounts_path.is_file():
            raise RcloneUploadError(
                "Cannot verify that the rclone temporary directory is RAM-backed."
            )
        resolved = path.resolve()
        candidates: list[tuple[Path, str]] = []
        for line in mounts_path.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) < 3:
                continue
            mount_point = Path(fields[1].replace("\\040", " ")).resolve()
            try:
                resolved.relative_to(mount_point)
            except ValueError:
                continue
            candidates.append((mount_point, fields[2]))
        if not candidates:
            raise RcloneUploadError(
                f"Cannot determine the filesystem for temporary path {path}."
            )
        _mount_point, filesystem = max(
            candidates,
            key=lambda candidate: len(candidate[0].parts),
        )
        if filesystem != "tmpfs":
            raise RcloneUploadError(
                f"Temporary path {path} is on {filesystem}, not tmpfs; refusing "
                "to write backup data to persistent INFRA-01 storage."
            )
