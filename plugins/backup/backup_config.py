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
class InfraBackupConfig:
    """Politique de sauvegarde logique locale d'INFRA-01."""

    enabled: bool = False
    schedule: str = "0 1 * * *"
    age_binary: str = "/usr/bin/age"
    age_recipient: str | None = None
    age_recipient_file: str = "/etc/ohana-agent/keys/infra-01.agepub"
    age_identity_file: str = "/etc/ohana-agent/keys/infra-01.agekey"
    recovery_remote_path: str = "icloud:Ohana/Recovery/infra-01.agekey"
    remote_retention_count: int = 0
    use_katsuyu: bool = True
    katsuyu_timeout_seconds: int = 3600
    max_artifact_bytes: int = 8 * 1024 * 1024 * 1024


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
    infra_01: InfraBackupConfig = field(default_factory=InfraBackupConfig)
