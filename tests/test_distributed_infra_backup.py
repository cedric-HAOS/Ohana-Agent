"""Tests for the job-bound Agent/Katsuyu INFRA backup data path."""

from __future__ import annotations

import hashlib
import io
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from administration.jobs import DistributedJobConflictError, DistributedJobRepository
from plugins.backup.backup_config import BackupConfig, InfraBackupConfig
from plugins.backup.distributed_infra_backup import DistributedInfraBackupTransfer
from plugins.backup.rclone_uploader import UploadReceipt


class FakeUploader:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def upload(
        self, stream: object, *, size_bytes: int, remote_path: str
    ) -> UploadReceipt:
        content = stream.read(size_bytes + 1)
        assert len(content) == size_bytes
        self.objects[remote_path] = content
        return UploadReceipt(
            remote_path=remote_path,
            size_bytes=size_bytes,
            sha256=hashlib.sha256(content).hexdigest(),
        )

    def prune_complete_backup_directories(
        self,
        remote_root: str,
        *,
        keep_count: int,
        protected_directory: str | None = None,
    ) -> int:
        assert remote_root.endswith("/infra-01")
        assert protected_directory == "20260820T120000Z"
        return 2

    def check_remote(self) -> None:
        return None


def _claimed_repository(tmp_path: Path) -> DistributedJobRepository:
    repository = DistributedJobRepository(tmp_path / "jobs.db")
    repository.register_worker(
        {
            "worker_id": "bubule",
            "capabilities": ["backup.infra"],
            "platform": "Windows 11",
            "worker_version": "0.3.0",
        }
    )
    repository.create(
        {
            "job_id": "11111111-1111-4111-8111-111111111111",
            "type": "backup.infra",
            "created_at": datetime.now(UTC).isoformat(),
            "parameters": {
                "backup_id": "20260820T120000Z",
                "recipient": "age1" + "q" * 58,
                "compression_level": 6,
            },
            "timeout": 600,
        }
    )
    claimed = repository.claim(
        {"worker_id": "bubule", "supported_types": ["backup.infra"]}
    )
    assert claimed.job is not None
    return repository


def test_artifact_is_authorized_by_job_owner_and_streamed_to_remote(
    tmp_path: Path,
) -> None:
    repository = _claimed_repository(tmp_path)
    uploader = FakeUploader()
    config = BackupConfig(
        rclone_remote="icloud:Ohana/Backups",
        infra_01=InfraBackupConfig(enabled=True, remote_retention_count=3),
    )
    transfer = DistributedInfraBackupTransfer(
        config,
        repository,
        sources=(tmp_path,),
        uploader=uploader,  # type: ignore[arg-type]
        version_resolver=lambda _name: "1.0.0",
    )
    artifact = b"age encrypted artifact"
    sha256 = hashlib.sha256(artifact).hexdigest()
    try:
        with pytest.raises(DistributedJobConflictError):
            transfer.receive_artifact(
                "11111111-1111-4111-8111-111111111111",
                "bubule",
                2,
                io.BytesIO(artifact),
                size_bytes=len(artifact),
                expected_sha256=sha256,
            )

        receipt = transfer.receive_artifact(
            "11111111-1111-4111-8111-111111111111",
            "bubule",
            1,
            io.BytesIO(artifact),
            size_bytes=len(artifact),
            expected_sha256=sha256,
        )
        assert receipt["sha256"] == sha256
        assert receipt["deleted_remote_backups"] == 2
        assert any(path.endswith("manifest.json") for path in uploader.objects)
    finally:
        repository.close()


def test_source_archive_is_uncompressed_and_contains_only_allowlisted_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _claimed_repository(tmp_path)
    source = tmp_path / "etc" / "ohana-agent"
    source.mkdir(parents=True)
    (source / "agent.yaml").write_text("version: 1\n", encoding="utf-8")
    temporary = tmp_path / "tmpfs"
    config = BackupConfig(
        temporary_directory=str(temporary),
        infra_01=InfraBackupConfig(enabled=True),
    )
    monkeypatch.setattr(
        "plugins.backup.distributed_infra_backup.RcloneStreamUploader._require_tmpfs",
        lambda _path: None,
    )
    transfer = DistributedInfraBackupTransfer(
        config,
        repository,
        sources=(source,),
        vision_database=tmp_path / "missing.db",
        uploader=FakeUploader(),  # type: ignore[arg-type]
        version_resolver=lambda _name: "1.0.0",
    )
    output = io.BytesIO()
    try:
        transfer.stream_source(
            "11111111-1111-4111-8111-111111111111", "bubule", 1, output
        )
    finally:
        repository.close()

    output.seek(0)
    with tarfile.open(fileobj=output, mode="r:") as archive:
        names = archive.getnames()
    assert "ohana-backup/descriptor.json" in names
    assert any(name.endswith("agent.yaml") for name in names)
