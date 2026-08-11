"""End-to-end HAOS backup orchestration without local archive storage."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from plugins.backup.backup_config import BackupConfig, BackupTarget
from plugins.backup.backup_secrets import resolve_backup_secret
from plugins.backup.home_assistant_backup_client import (
    HomeAssistantBackupClient,
)
from plugins.backup.rclone_uploader import RcloneStreamUploader


class BackupExecutionError(RuntimeError):
    """Failure annotated with the backup stage that could not complete."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True, slots=True)
class BackupExecutionResult:
    """Successful backup, cloud validation and local rotation details."""

    target_id: str
    backup_slug: str
    backup_name: str
    remote_path: str
    size_bytes: int
    sha256: str
    deleted_local_backups: int


class BackupClientFactory(Protocol):
    """Create one authenticated client for a configured target."""

    def __call__(
        self,
        target: BackupTarget,
        token: str,
    ) -> HomeAssistantBackupClient: ...


class BackupCoordinator:
    """Create, stream, validate and rotate one managed HAOS backup."""

    def __init__(
        self,
        config: BackupConfig,
        *,
        client_factory: BackupClientFactory = HomeAssistantBackupClient,
        uploader: RcloneStreamUploader | None = None,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._uploader = uploader or RcloneStreamUploader(config)

    def run(
        self,
        target: BackupTarget,
        *,
        now: datetime | None = None,
    ) -> BackupExecutionResult:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        token = target.token or self._secret(target.token_environment_variable)
        if not token:
            source = (
                f" in {target.token_environment_variable}"
                if target.token_environment_variable
                else ""
            )
            raise BackupExecutionError(
                "authentication",
                f"Missing Home Assistant token{source} for {target.label}.",
            )
        password = target.password or self._secret(target.password_environment_variable)
        if not password:
            source = (
                f" in {target.password_environment_variable}"
                if target.password_environment_variable
                else ""
            )
            raise BackupExecutionError(
                "encryption",
                f"Missing backup encryption password{source} for {target.label}.",
            )
        client = self._client_factory(target, token)
        managed_prefix = f"Ohana-{target.id}-"

        try:
            previous = tuple(
                backup
                for backup in client.list_backups()
                if backup.name is not None and backup.name.startswith(managed_prefix)
            )
        except Exception as error:
            raise BackupExecutionError("inventory", str(error)) from error

        try:
            client.run_pre_backup_action()
        except Exception as error:
            raise BackupExecutionError("preparation", str(error)) from error

        timestamp = current_time.strftime("%Y%m%dT%H%M%SZ")
        backup_name = f"{managed_prefix}{timestamp}"
        try:
            backup = client.create_full_backup(backup_name, password=password)
        except Exception as error:
            raise BackupExecutionError("creation", str(error)) from error

        safe_slug = self._safe_component(backup.slug)
        archive_name = f"{timestamp}_{safe_slug}.tar"
        remote_path = (
            f"{self._config.rclone_remote}/{target.id}/"
            f"{current_time:%Y/%m}/{archive_name}"
        )
        try:
            with client.download(backup.slug) as download:
                receipt = self._uploader.upload(
                    download.stream,
                    size_bytes=download.size_bytes,
                    remote_path=remote_path,
                )
        except Exception as error:
            raise BackupExecutionError("upload", str(error)) from error

        checksum_body = f"{receipt.sha256}  {archive_name}\n".encode("ascii")
        try:
            self._uploader.upload(
                io.BytesIO(checksum_body),
                size_bytes=len(checksum_body),
                remote_path=f"{remote_path}.sha256",
            )
        except Exception as error:
            raise BackupExecutionError("checksum", str(error)) from error

        deleted = 0
        try:
            for old_backup in previous:
                if old_backup.slug == backup.slug:
                    continue
                client.delete(old_backup.slug)
                deleted += 1
        except Exception as error:
            raise BackupExecutionError("rotation", str(error)) from error

        return BackupExecutionResult(
            target_id=target.id,
            backup_slug=backup.slug,
            backup_name=backup_name,
            remote_path=remote_path,
            size_bytes=receipt.size_bytes,
            sha256=receipt.sha256,
            deleted_local_backups=deleted,
        )

    def preflight(self, target: BackupTarget) -> int:
        """Check credentials, HAOS access and rclone without creating a backup."""
        token = target.token or self._secret(target.token_environment_variable)
        if not token:
            source = (
                f" in {target.token_environment_variable}"
                if target.token_environment_variable
                else ""
            )
            raise BackupExecutionError(
                "authentication",
                f"Missing Home Assistant token{source} for {target.label}.",
            )
        if not (target.password or self._secret(target.password_environment_variable)):
            source = (
                f" in {target.password_environment_variable}"
                if target.password_environment_variable
                else ""
            )
            raise BackupExecutionError(
                "encryption",
                f"Missing backup encryption password{source} for {target.label}.",
            )
        try:
            backups = self._client_factory(target, token).list_backups()
        except Exception as error:
            raise BackupExecutionError("inventory", str(error)) from error
        try:
            self._uploader.check_remote()
        except Exception as error:
            raise BackupExecutionError("remote", str(error)) from error
        return len(backups)

    def _secret(self, name: str | None) -> str | None:
        if not name:
            return None
        try:
            return resolve_backup_secret(self._config.environment_file, name)
        except OSError as error:
            raise BackupExecutionError(
                "authentication",
                "Unable to read backup environment file "
                f"{self._config.environment_file}: {error}",
            ) from error

    @staticmethod
    def _safe_component(value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", value.strip())
        if not safe:
            raise BackupExecutionError("creation", "Backup slug is invalid.")
        return safe
