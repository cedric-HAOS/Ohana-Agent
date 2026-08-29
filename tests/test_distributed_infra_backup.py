"""Tests for the job-bound Agent/Katsuyu INFRA backup data path."""

from __future__ import annotations

import hashlib
import io
import sqlite3
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from administration.jobs import DistributedJobConflictError, DistributedJobRepository
from plugins.backup.backup_config import BackupConfig, InfraBackupConfig
from plugins.backup.distributed_infra_backup import (
    DistributedInfraBackupCoordinator,
    DistributedInfraBackupTransfer,
)
from plugins.backup.infra_backup_coordinator import InfraBackupCoordinator
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


def test_coordinator_waits_for_the_effective_grouped_job_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = BackupConfig(
        infra_01=InfraBackupConfig(enabled=True, katsuyu_timeout_seconds=3600)
    )
    transfer = SimpleNamespace(
        preflight=lambda: "age1" + "q" * 58,
        local=SimpleNamespace(_upload_recovery_identity=lambda: None),
    )
    created_payloads: list[dict[str, object]] = []

    def create_job(payload: dict[str, object]) -> object:
        created_payloads.append(payload)
        return SimpleNamespace(timeout=7380)

    result = {
        "remote_path": "icloud:Ohana/Backups/infra-01/20260829T000000Z",
        "size_bytes": 1234,
        "sha256": "a" * 64,
        "deleted_remote_backups": 1,
    }
    monotonic_values = iter((100.0, 5000.0))
    monkeypatch.setattr(
        "plugins.backup.distributed_infra_backup.monotonic",
        lambda: next(monotonic_values),
    )
    coordinator = DistributedInfraBackupCoordinator(
        config,
        transfer,  # type: ignore[arg-type]
        create_job=create_job,
        read_job=lambda _job_id: SimpleNamespace(
            status="SUCCEEDED", result=result, error=None
        ),
    )

    completed = coordinator.run(now=datetime(2026, 8, 29, tzinfo=UTC))

    assert created_payloads[0]["timeout"] == 3600
    assert completed.remote_directory == result["remote_path"]
    assert completed.sha256 == "a" * 64


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
        assert any(
            path.endswith("/20260820T120000Z.tar.age") for path in uploader.objects
        )
        assert any(path.endswith("manifest.json") for path in uploader.objects)
    finally:
        repository.close()


def test_artifact_metadata_is_resolved_before_remote_upload(tmp_path: Path) -> None:
    repository = _claimed_repository(tmp_path)
    uploader = FakeUploader()

    def unavailable(distribution: str) -> str:
        if distribution == "ohana-vision":
            raise OSError("Vision timeout")
        return "1.0.0"

    transfer = DistributedInfraBackupTransfer(
        BackupConfig(infra_01=InfraBackupConfig(enabled=True)),
        repository,
        sources=(tmp_path,),
        uploader=uploader,  # type: ignore[arg-type]
        version_resolver=unavailable,
    )
    artifact = b"age encrypted artifact"
    try:
        with pytest.raises(OSError, match="Vision timeout"):
            transfer.receive_artifact(
                "11111111-1111-4111-8111-111111111111",
                "bubule",
                1,
                io.BytesIO(artifact),
                size_bytes=len(artifact),
                expected_sha256=hashlib.sha256(artifact).hexdigest(),
            )
        assert uploader.objects == {}
    finally:
        repository.close()


def test_source_archive_is_uncompressed_and_contains_only_allowlisted_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _claimed_repository(tmp_path)
    source = tmp_path / "etc" / "ohana-agent"
    source.mkdir(parents=True)
    (source / "agent.yaml").write_text("version: 1\n", encoding="utf-8")
    database = tmp_path / "vision.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE observations(value TEXT)")
    connection.commit()
    connection.close()
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
        vision_database=database,
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
    assert "var/lib/ohana-vision/vision.db" in names
    assert any(name.endswith("agent.yaml") for name in names)


def test_root_only_worker_ca_material_is_excluded() -> None:
    ca_key = tarfile.TarInfo("etc/ohana-agent/tls/ca.key")
    ca_key.type = tarfile.REGTYPE
    ca_serial = tarfile.TarInfo("etc/ohana-agent/tls/ca.srl")
    ca_serial.type = tarfile.REGTYPE
    worker_key = tarfile.TarInfo("etc/ohana-agent/tls/worker.key")
    worker_key.type = tarfile.REGTYPE

    assert InfraBackupCoordinator._regular_member(ca_key) is None
    assert InfraBackupCoordinator._regular_member(ca_serial) is None
    assert InfraBackupCoordinator._regular_member(worker_key) is worker_key


def test_source_archive_requires_vision_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _claimed_repository(tmp_path)
    source = tmp_path / "etc" / "ohana-agent"
    source.mkdir(parents=True)
    temporary = tmp_path / "tmpfs"
    monkeypatch.setattr(
        "plugins.backup.distributed_infra_backup.RcloneStreamUploader._require_tmpfs",
        lambda _path: None,
    )
    transfer = DistributedInfraBackupTransfer(
        BackupConfig(
            temporary_directory=str(temporary),
            infra_01=InfraBackupConfig(enabled=True),
        ),
        repository,
        sources=(source,),
        vision_database=tmp_path / "missing.db",
        uploader=FakeUploader(),  # type: ignore[arg-type]
        version_resolver=lambda _name: "1.0.0",
    )
    try:
        with pytest.raises(RuntimeError, match="Missing INFRA-01 backup source"):
            transfer.stream_source(
                "11111111-1111-4111-8111-111111111111", "bubule", 1, io.BytesIO()
            )
    finally:
        repository.close()


def test_source_snapshot_fits_when_database_contains_many_free_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _claimed_repository(tmp_path)
    source = tmp_path / "etc" / "ohana-agent"
    source.mkdir(parents=True)
    (source / "agent.yaml").write_text("version: 1\n", encoding="utf-8")
    database = tmp_path / "vision.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE observations(value BLOB)")
    connection.execute("INSERT INTO observations VALUES (zeroblob(25165824))")
    connection.commit()
    connection.execute("DELETE FROM observations")
    connection.commit()
    connection.close()
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
        vision_database=database,
        uploader=FakeUploader(),  # type: ignore[arg-type]
        version_resolver=lambda _name: "1.0.0",
    )
    compact_size = transfer.local._compact_database_size()
    available = compact_size + 17 * 1024 * 1024
    assert database.stat().st_size > available
    monkeypatch.setattr(
        "plugins.backup.distributed_infra_backup.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=available),
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
        snapshot = archive.extractfile("var/lib/ohana-vision/vision.db")
        assert snapshot is not None
        assert len(snapshot.read()) < available


def test_vision_snapshot_retries_a_transient_sqlite_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _claimed_repository(tmp_path)
    database = tmp_path / "vision.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE observations(value TEXT)")
    connection.execute("INSERT INTO observations VALUES ('healthy')")
    connection.commit()
    connection.close()
    real_connect = sqlite3.connect
    attempts = 0

    class BusyConnection:
        def execute(self, _statement: str, _parameters: object = ()) -> object:
            raise sqlite3.OperationalError("database is locked")

        def close(self) -> None:
            return None

    def connect(*args: object, **kwargs: object) -> object:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return BusyConnection()
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(
        "plugins.backup.distributed_infra_backup.sqlite3.connect",
        connect,
    )
    waits: list[float] = []
    transfer = DistributedInfraBackupTransfer(
        BackupConfig(infra_01=InfraBackupConfig(enabled=True)),
        repository,
        sources=(tmp_path,),
        vision_database=database,
        uploader=FakeUploader(),  # type: ignore[arg-type]
        snapshot_retry_delay_seconds=0.25,
        wait=waits.append,
    )
    snapshot = tmp_path / "snapshot.db"
    try:
        transfer._snapshot_vision(snapshot)
    finally:
        repository.close()

    assert attempts == 2
    assert waits == [0.25]
    restored = sqlite3.connect(snapshot)
    try:
        assert restored.execute("SELECT value FROM observations").fetchone() == (
            "healthy",
        )
    finally:
        restored.close()
