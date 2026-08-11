"""Runtime configuration for HAOS streaming backups."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class BackupAction:
    """Optional Home Assistant action executed before backup creation."""

    domain: str
    service: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BackupTarget:
    """One Home Assistant OS backup target."""

    id: str
    label: str
    url: str
    schedule: str
    token: str | None = None
    password: str | None = None
    token_environment_variable: str | None = None
    password_environment_variable: str | None = None
    enabled: bool = True
    verify_tls: bool = True
    timeout: float = 300.0
    pre_backup_action: BackupAction | None = None


@dataclass(frozen=True, slots=True)
class BackupConfig:
    """Complete runtime backup policy."""

    targets: tuple[BackupTarget, ...] = ()
    rclone_binary: str = "/usr/bin/rclone"
    rclone_config_path: str = "/etc/ohana-agent/rclone.conf"
    rclone_remote: str = "icloud:Ohana/Backups"
    environment_file: str = "/etc/ohana-agent/backup.env"
    temporary_directory: str = "/run/ohana-agent/backup"
    require_tmpfs: bool = True
    chunk_size_bytes: int = 1024 * 1024
