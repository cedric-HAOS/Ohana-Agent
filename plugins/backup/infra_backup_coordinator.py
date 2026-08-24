"""Sauvegarde logique chiffrée d'INFRA-01 vers iCloud."""

from __future__ import annotations

import errno
import io
import json
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from plugins.backup.backup_config import BackupConfig
from plugins.backup.backup_coordinator import BackupExecutionError
from plugins.backup.rclone_uploader import RcloneStreamUploader

INFRA_SOURCES = (
    Path("/etc/ohana-agent"),
    Path("/etc/ohana-vision"),
    Path("/etc/dnsmasq.d"),
    Path("/etc/chrony/chrony.conf"),
)
VISION_DATABASE = Path("/var/lib/ohana-vision/vision.db")
INFRA_EXCLUDED_MEMBERS = frozenset(
    {
        "etc/ohana-agent/tls/ca.key",
        "etc/ohana-agent/tls/ca.srl",
    }
)
INFRA_REQUIRED_MEMBERS = (
    "etc/ohana-agent",
    "etc/ohana-vision",
    "etc/dnsmasq.d",
    "etc/chrony/chrony.conf",
    "var/lib/ohana-vision/vision.db",
)
VISION_VERSION_URL = "http://127.0.0.1:8000/api/version"
VISION_VERSION_TIMEOUT_SECONDS = 5.0
MINIMUM_ARCHIVE_HEADROOM_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class InfraBackupResult:
    """Résultat d'une sauvegarde INFRA-01 validée à distance."""

    backup_id: str
    remote_directory: str
    size_bytes: int
    sha256: str
    deleted_remote_backups: int = 0


class InfraBackupCoordinator:
    """Créer en tmpfs une archive age, la valider et publier son manifeste."""

    def __init__(
        self,
        config: BackupConfig,
        *,
        uploader: RcloneStreamUploader | None = None,
        sources: tuple[Path, ...] = INFRA_SOURCES,
        vision_database: Path = VISION_DATABASE,
        version_resolver: Any | None = None,
        vision_version_reader: Any = urlopen,
        popen_factory: Any = subprocess.Popen,
    ) -> None:
        self._config = config
        self._infra = config.infra_01
        self._uploader = uploader or RcloneStreamUploader(config)
        self._sources = sources
        self._vision_database = vision_database
        self._version_resolver = version_resolver
        self._vision_version_reader = vision_version_reader
        self._popen_factory = popen_factory

    def run(self, *, now: datetime | None = None) -> InfraBackupResult:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        recipient = self._preflight_local()
        self._upload_recovery_identity()
        backup_id = current.strftime("%Y%m%dT%H%M%SZ")
        remote_directory = f"{self._config.rclone_remote}/infra-01/{backup_id}"
        temporary_root = Path(self._config.temporary_directory)
        RcloneStreamUploader._require_tmpfs(temporary_root)
        temporary_root.mkdir(parents=True, exist_ok=True)
        self._ensure_temporary_capacity(temporary_root)
        agent_version = self._installed_version("ohana-agent")
        vision_version = self._installed_version("ohana-vision")

        try:
            with tempfile.TemporaryDirectory(
                prefix="infra-01-",
                dir=temporary_root,
            ) as directory:
                runtime = Path(directory)
                snapshot = runtime / "vision.db"
                self._snapshot_vision(snapshot)
                descriptor = runtime / "descriptor.json"
                descriptor.write_bytes(
                    self._descriptor(
                        backup_id=backup_id,
                        current=current,
                        agent_version=agent_version,
                        vision_version=vision_version,
                    )
                )
                archive = runtime / f"{backup_id}.tar.age"
                self._create_encrypted_archive(
                    archive,
                    snapshot=snapshot,
                    descriptor=descriptor,
                    recipient=recipient,
                )
                size = archive.stat().st_size
                with archive.open("rb") as stream:
                    receipt = self._uploader.upload(
                        stream,
                        size_bytes=size,
                        remote_path=f"{remote_directory}/{archive.name}",
                    )
                manifest = self._manifest(
                    backup_id=backup_id,
                    current=current,
                    filename=archive.name,
                    size_bytes=receipt.size_bytes,
                    sha256=receipt.sha256,
                    agent_version=agent_version,
                    vision_version=vision_version,
                )
                self._uploader.upload(
                    io.BytesIO(manifest),
                    size_bytes=len(manifest),
                    remote_path=f"{remote_directory}/manifest.json",
                )
                deleted = self._uploader.prune_complete_backup_directories(
                    f"{self._config.rclone_remote}/infra-01",
                    keep_count=self._infra.remote_retention_count,
                    protected_directory=backup_id,
                )
        except BackupExecutionError:
            raise
        except Exception as error:
            raise BackupExecutionError("infra-01", str(error)) from error

        return InfraBackupResult(
            backup_id=backup_id,
            remote_directory=remote_directory,
            size_bytes=receipt.size_bytes,
            sha256=receipt.sha256,
            deleted_remote_backups=deleted,
        )

    def preflight(self) -> None:
        """Valider les sources, age, tmpfs et iCloud sans créer d'archive."""

        self._preflight_local()
        temporary_root = Path(self._config.temporary_directory)
        RcloneStreamUploader._require_tmpfs(temporary_root)
        self._ensure_temporary_capacity(temporary_root)
        self._uploader.check_remote()

    def _preflight_local(self) -> str:
        if not self._infra.enabled:
            raise BackupExecutionError("configuration", "INFRA-01 backup is disabled.")
        if not Path(self._infra.age_binary).is_file():
            raise BackupExecutionError(
                "encryption",
                f"age is not installed at {self._infra.age_binary}.",
            )
        missing = tuple(path for path in self._sources if not path.exists())
        if missing:
            raise BackupExecutionError(
                "inventory",
                "Missing INFRA-01 backup source(s): "
                + ", ".join(str(path) for path in missing),
            )
        return self._age_recipient()

    def _age_recipient(self) -> str:
        recipient_path = Path(self._infra.age_recipient_file)
        try:
            recipient = recipient_path.read_text(encoding="utf-8").strip()
        except OSError:
            # Temporary compatibility with pre-managed configurations.
            recipient = str(self._infra.age_recipient or "").strip()
        if not recipient:
            raise BackupExecutionError(
                "encryption",
                f"Age public recipient is unavailable: {recipient_path}.",
            )
        if not recipient.startswith("age1"):
            raise BackupExecutionError("encryption", "Age public recipient is invalid.")
        return recipient

    def _upload_recovery_identity(self) -> None:
        identity = Path(self._infra.age_identity_file)
        if not identity.is_file():
            raise BackupExecutionError(
                "recovery",
                f"Age recovery identity is unavailable: {identity}.",
            )
        with identity.open("rb") as stream:
            self._uploader.upload(
                stream,
                size_bytes=identity.stat().st_size,
                remote_path=self._infra.recovery_remote_path,
            )

    def _snapshot_vision(self, destination: Path) -> None:
        if not self._vision_database.is_file():
            return
        source = sqlite3.connect(
            f"file:{self._vision_database.as_posix()}?mode=ro",
            uri=True,
        )
        try:
            source.execute("VACUUM INTO ?", (str(destination),))
        finally:
            source.close()

    def _create_encrypted_archive(
        self,
        destination: Path,
        *,
        snapshot: Path,
        descriptor: Path,
        recipient: str,
    ) -> None:
        process = self._popen_factory(
            (
                self._infra.age_binary,
                "--encrypt",
                "--recipient",
                recipient,
                "--output",
                str(destination),
                "-",
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if process.stdin is None:
            process.kill()
            raise BackupExecutionError("encryption", "age did not expose stdin.")
        try:
            with tarfile.open(fileobj=process.stdin, mode="w|gz") as archive:
                for source in self._sources:
                    archive.add(
                        source,
                        arcname=source.as_posix().lstrip("/"),
                        recursive=True,
                        filter=self._regular_member,
                    )
                if snapshot.is_file():
                    archive.add(
                        snapshot,
                        arcname="var/lib/ohana-vision/vision.db",
                        recursive=False,
                        filter=self._regular_member,
                    )
                archive.add(
                    descriptor,
                    arcname="ohana-backup/descriptor.json",
                    recursive=False,
                    filter=self._regular_member,
                )
            process.stdin.close()
            process.stdin = None
            _stdout, stderr = process.communicate()
        except Exception as error:
            pipe_failed = isinstance(error, BrokenPipeError) or (
                isinstance(error, OSError) and error.errno == errno.EPIPE
            )
            try:
                process.stdin.close()
            except OSError:
                pass
            process.stdin = None
            if process.poll() is None:
                process.kill()
            _stdout, stderr = process.communicate()
            if pipe_failed and process.returncode != 0:
                detail = (stderr or b"unknown age error").decode(errors="replace")
                raise BackupExecutionError("encryption", detail[:500]) from error
            raise
        if process.returncode != 0:
            detail = (stderr or b"unknown age error").decode(errors="replace")
            raise BackupExecutionError("encryption", detail[:500])

    def _ensure_temporary_capacity(self, temporary_root: Path) -> None:
        """Ensure the tmpfs can hold the SQLite snapshot and archive headroom."""

        database_size = self._compact_database_size()
        required = (
            database_size * 2
            + self._source_size_bytes()
            + MINIMUM_ARCHIVE_HEADROOM_BYTES
        )
        available = shutil.disk_usage(temporary_root).free
        if available < required:
            raise BackupExecutionError(
                "storage",
                "Insufficient tmpfs space for INFRA-01 backup: "
                f"{available} bytes available, at least {required} required.",
            )

    def _compact_database_size(self) -> int:
        if not self._vision_database.is_file():
            return 0
        connection = sqlite3.connect(
            f"file:{self._vision_database.as_posix()}?mode=ro",
            uri=True,
        )
        try:
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            free_pages = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        finally:
            connection.close()
        return max(page_count - free_pages, 0) * page_size

    def _source_size_bytes(self) -> int:
        total = 0
        for source in self._sources:
            candidates = source.rglob("*") if source.is_dir() else (source,)
            for candidate in candidates:
                archive_name = candidate.as_posix().lstrip("/")
                if archive_name in INFRA_EXCLUDED_MEMBERS:
                    continue
                try:
                    if candidate.is_file() and not candidate.is_symlink():
                        total += candidate.stat().st_size
                except OSError:
                    continue
        return total

    @staticmethod
    def _regular_member(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if member.name.rstrip("/") in INFRA_EXCLUDED_MEMBERS:
            return None
        if member.isfile() or member.isdir():
            return member
        return None

    def _manifest(
        self,
        *,
        backup_id: str,
        current: datetime,
        filename: str,
        size_bytes: int,
        sha256: str,
        agent_version: str,
        vision_version: str,
    ) -> bytes:
        payload = {
            "schema_version": 1,
            "backup_id": backup_id,
            "created_at": current.isoformat().replace("+00:00", "Z"),
            "profile": "infra-01",
            "platform_version": None,
            "agent_version": agent_version,
            "vision_version": vision_version,
            "archive": {
                "filename": filename,
                "size_bytes": size_bytes,
                "sha256": sha256,
                "encryption": "age",
            },
        }
        return (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()

    @staticmethod
    def _descriptor(
        *,
        backup_id: str,
        current: datetime,
        agent_version: str,
        vision_version: str,
    ) -> bytes:
        """Embed identity metadata inside the age-protected archive."""

        payload = {
            "schema_version": 1,
            "backup_id": backup_id,
            "created_at": current.isoformat().replace("+00:00", "Z"),
            "profile": "infra-01",
            "platform_version": None,
            "agent_version": agent_version,
            "vision_version": vision_version,
            "contents": list(INFRA_REQUIRED_MEMBERS),
        }
        return (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()

    def _installed_version(self, distribution: str) -> str:
        if self._version_resolver is not None:
            try:
                return str(self._version_resolver(distribution))
            except PackageNotFoundError as error:
                raise BackupExecutionError(
                    "inventory",
                    f"Installed version unavailable for {distribution}.",
                ) from error
        if distribution == "ohana-vision":
            return self._vision_version()
        try:
            return str(version(distribution))
        except PackageNotFoundError as error:
            raise BackupExecutionError(
                "inventory",
                f"Installed version unavailable for {distribution}.",
            ) from error

    def _vision_version(self) -> str:
        try:
            with self._vision_version_reader(
                VISION_VERSION_URL,
                timeout=VISION_VERSION_TIMEOUT_SECONDS,
            ) as response:
                payload = json.loads(response.read())
        except (
            OSError,
            URLError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ) as error:
            raise BackupExecutionError(
                "inventory",
                "Installed version unavailable for ohana-vision.",
            ) from error
        installed = payload.get("version") if isinstance(payload, dict) else None
        if not isinstance(installed, str) or not installed.strip():
            raise BackupExecutionError(
                "inventory",
                "Installed version unavailable for ohana-vision.",
            )
        return installed.strip()
