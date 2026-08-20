"""Job-bound INFRA-01 backup transfers over the existing Katsuyu HTTPS channel."""

from __future__ import annotations

import io
import shutil
import sqlite3
import tarfile
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep
from typing import Any, BinaryIO
from uuid import uuid4

from administration.jobs import DistributedJobRepository
from administration.models import DistributedJobStatus
from plugins.backup.backup_config import BackupConfig
from plugins.backup.backup_coordinator import BackupExecutionError
from plugins.backup.infra_backup_coordinator import (
    INFRA_SOURCES,
    VISION_DATABASE,
    InfraBackupCoordinator,
    InfraBackupResult,
)
from plugins.backup.rclone_uploader import RcloneStreamUploader


class DistributedInfraBackupTransfer:
    """Serve one allowlisted source tar and accept its encrypted job artifact."""

    def __init__(
        self,
        config: BackupConfig,
        repository: DistributedJobRepository,
        *,
        sources: tuple[Path, ...] = INFRA_SOURCES,
        vision_database: Path = VISION_DATABASE,
        uploader: RcloneStreamUploader | None = None,
        version_resolver: Any | None = None,
        vision_version_reader: Any | None = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.sources = sources
        self.vision_database = vision_database
        self.uploader = uploader or RcloneStreamUploader(config)
        arguments: dict[str, Any] = {
            "sources": sources,
            "vision_database": vision_database,
            "uploader": self.uploader,
            "version_resolver": version_resolver,
        }
        if vision_version_reader is not None:
            arguments["vision_version_reader"] = vision_version_reader
        self.local = InfraBackupCoordinator(config, **arguments)

    def authorize(self, job_id: str, worker_id: str, attempt: int) -> object:
        return self.repository.authorize_job_transfer(
            job_id, worker_id=worker_id, attempt=attempt
        )

    def stream_source(
        self, job_id: str, worker_id: str, attempt: int, output: BinaryIO
    ) -> None:
        """Stream an uncompressed deterministic source archive without staging it."""
        job = self.repository.authorize_job_transfer(
            job_id, worker_id=worker_id, attempt=attempt
        )
        backup_id = str(job.parameters["backup_id"])
        temporary_root = Path(self.config.temporary_directory)
        RcloneStreamUploader._require_tmpfs(temporary_root)
        temporary_root.mkdir(parents=True, exist_ok=True)
        self._ensure_snapshot_capacity(temporary_root)
        with tempfile.TemporaryDirectory(
            prefix="infra-source-", dir=temporary_root
        ) as directory:
            runtime = Path(directory)
            snapshot = runtime / "vision.db"
            self._snapshot_vision(snapshot)
            current = datetime.strptime(backup_id, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=UTC
            )
            descriptor = runtime / "descriptor.json"
            descriptor.write_bytes(
                self.local._descriptor(
                    backup_id=backup_id,
                    current=current,
                    agent_version=self.local._installed_version("ohana-agent"),
                    vision_version=self.local._installed_version("ohana-vision"),
                )
            )
            with tarfile.open(fileobj=output, mode="w|") as archive:
                for source in self.sources:
                    archive.add(
                        source,
                        arcname=source.as_posix().lstrip("/"),
                        recursive=True,
                        filter=self.local._regular_member,
                    )
                if snapshot.is_file():
                    archive.add(
                        snapshot,
                        arcname="var/lib/ohana-vision/vision.db",
                        recursive=False,
                        filter=self.local._regular_member,
                    )
                archive.add(
                    descriptor,
                    arcname="ohana-backup/descriptor.json",
                    recursive=False,
                    filter=self.local._regular_member,
                )

    def receive_artifact(
        self,
        job_id: str,
        worker_id: str,
        attempt: int,
        stream: BinaryIO,
        *,
        size_bytes: int,
        expected_sha256: str,
    ) -> dict[str, object]:
        """Stream a bounded artifact directly into rclone and publish its manifest."""
        job = self.repository.authorize_job_transfer(
            job_id, worker_id=worker_id, attempt=attempt
        )
        if size_bytes < 1 or size_bytes > self.config.infra_01.max_artifact_bytes:
            raise ValueError("distributed backup artifact size is invalid")
        if len(expected_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in expected_sha256
        ):
            raise ValueError("distributed backup artifact SHA-256 is invalid")
        backup_id = str(job.parameters["backup_id"])
        filename = f"{backup_id}.tar.gz.age"
        remote_directory = f"{self.config.rclone_remote}/infra-01/{backup_id}"
        receipt = self.uploader.upload(
            stream,
            size_bytes=size_bytes,
            remote_path=f"{remote_directory}/{filename}",
        )
        if receipt.sha256 != expected_sha256:
            raise BackupExecutionError(
                "integrity", "Katsuyu artifact SHA-256 does not match the upload."
            )
        current = datetime.strptime(backup_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        manifest = self.local._manifest(
            backup_id=backup_id,
            current=current,
            filename=filename,
            size_bytes=receipt.size_bytes,
            sha256=receipt.sha256,
            agent_version=self.local._installed_version("ohana-agent"),
            vision_version=self.local._installed_version("ohana-vision"),
        )
        self.uploader.upload(
            io.BytesIO(manifest),
            size_bytes=len(manifest),
            remote_path=f"{remote_directory}/manifest.json",
        )
        deleted = self.uploader.prune_complete_backup_directories(
            f"{self.config.rclone_remote}/infra-01",
            keep_count=self.config.infra_01.remote_retention_count,
            protected_directory=backup_id,
        )
        return {
            "remote_path": remote_directory,
            "sha256": receipt.sha256,
            "size_bytes": receipt.size_bytes,
            "deleted_remote_backups": deleted,
        }

    def preflight(self) -> str:
        """Validate only work that remains on INFRA-01 for the distributed flow."""
        if not self.config.infra_01.enabled:
            raise BackupExecutionError("configuration", "INFRA-01 backup is disabled.")
        missing = tuple(path for path in self.sources if not path.exists())
        if missing:
            raise BackupExecutionError(
                "inventory",
                "Missing INFRA-01 backup source(s): "
                + ", ".join(str(path) for path in missing),
            )
        recipient = self.local._age_recipient()
        temporary_root = Path(self.config.temporary_directory)
        RcloneStreamUploader._require_tmpfs(temporary_root)
        temporary_root.mkdir(parents=True, exist_ok=True)
        self._ensure_snapshot_capacity(temporary_root)
        self.uploader.check_remote()
        return recipient

    def _ensure_snapshot_capacity(self, temporary_root: Path) -> None:
        required = self.local._compact_database_size() + 16 * 1024 * 1024
        available = shutil.disk_usage(temporary_root).free
        if available < required:
            raise BackupExecutionError(
                "storage",
                "Insufficient tmpfs space for the distributed SQLite snapshot: "
                f"{available} bytes available, at least {required} required.",
            )

    def _snapshot_vision(self, destination: Path) -> None:
        if not self.vision_database.is_file():
            return
        source = sqlite3.connect(
            f"file:{self.vision_database.as_posix()}?mode=ro", uri=True
        )
        target = sqlite3.connect(destination)
        try:
            source.backup(target, pages=128, sleep=0.01)
        finally:
            target.close()
            source.close()


class DistributedInfraBackupCoordinator:
    """Queue, wait for, and verify the single deterministic Katsuyu backup job."""

    def __init__(
        self,
        config: BackupConfig,
        transfer: DistributedInfraBackupTransfer,
        *,
        create_job: Callable[[dict[str, object]], object],
        read_job: Callable[[str], object],
        wait: Callable[[float], None] = sleep,
    ) -> None:
        self.config = config
        self.transfer = transfer
        self.create_job = create_job
        self.read_job = read_job
        self.wait = wait

    def preflight(self) -> None:
        self.transfer.preflight()

    def run(self, *, now: datetime | None = None) -> InfraBackupResult:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        recipient = self.transfer.preflight()
        self.transfer.local._upload_recovery_identity()
        backup_id = current.strftime("%Y%m%dT%H%M%SZ")
        job_id = str(uuid4())
        self.create_job(
            {
                "protocol_version": 1,
                "job_id": job_id,
                "type": "backup.infra",
                "created_at": current.isoformat(),
                "parameters": {
                    "backup_id": backup_id,
                    "recipient": recipient,
                    "compression_level": 6,
                },
                "timeout": self.config.infra_01.katsuyu_timeout_seconds,
            }
        )
        deadline = monotonic() + self.config.infra_01.katsuyu_timeout_seconds + 10
        while monotonic() < deadline:
            document = self.read_job(job_id)
            status = DistributedJobStatus(document.status)
            if status == DistributedJobStatus.SUCCEEDED:
                result = document.result
                return InfraBackupResult(
                    backup_id=backup_id,
                    remote_directory=str(result["remote_path"]),
                    size_bytes=int(result["size_bytes"]),
                    sha256=str(result["sha256"]),
                    deleted_remote_backups=int(result["deleted_remote_backups"]),
                )
            if status in {
                DistributedJobStatus.FAILED,
                DistributedJobStatus.CANCELLED,
                DistributedJobStatus.TIMEOUT,
            }:
                detail = document.error.message if document.error else status.value
                raise BackupExecutionError("katsuyu", detail)
            self.wait(2)
        raise BackupExecutionError("katsuyu", "Distributed backup wait timed out.")
