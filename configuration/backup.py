"""HAOS backup plugin configuration models."""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field, PositiveFloat, field_validator, model_validator

from configuration.base import Config


class BackupActionConfig(Config):
    """Optional Home Assistant action executed before a full backup."""

    domain: str
    service: str
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("domain", "service")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Backup action fields must not be empty.")
        return normalized


class BackupTargetPluginConfig(Config):
    """One Home Assistant OS instance to protect."""

    id: str
    label: str
    enabled: bool = True
    url: str
    token: str | None = None
    password: str | None = None
    token_environment_variable: str | None = None
    password_environment_variable: str | None = None
    schedule: str
    verify_tls: bool = True
    timeout: PositiveFloat = 300.0
    pre_backup_action: BackupActionConfig | None = None

    @field_validator(
        "label",
        "schedule",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Backup target fields must not be empty.")
        return normalized

    @field_validator(
        "token",
        "password",
        "token_environment_variable",
        "password_environment_variable",
    )
    @classmethod
    def normalize_optional_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value if value.strip() else None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", normalized):
            raise ValueError(
                "Backup target id must use lowercase letters, digits and hyphens."
            )
        return normalized

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("Backup target URL must start with http:// or https://.")
        return normalized


class InfraBackupPluginConfig(Config):
    """Sauvegarde logique chiffrée de la machine INFRA-01."""

    enabled: bool = False
    schedule: str = "0 1 * * *"
    age_binary: str = "/usr/bin/age"
    age_recipient: str | None = None
    remote_retention_count: int = Field(default=0, ge=0, le=365)

    @field_validator("schedule", "age_binary")
    @classmethod
    def validate_infra_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("INFRA-01 backup fields must not be empty.")
        return normalized

    @field_validator("age_recipient")
    @classmethod
    def normalize_age_recipient(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def validate_encryption(self) -> InfraBackupPluginConfig:
        if self.enabled and not self.age_recipient:
            raise ValueError("Enabled INFRA-01 backup requires an age recipient.")
        return self


class BackupPluginConfig(Config):
    """Global HAOS-to-iCloud streaming backup policy."""

    enabled: bool = False
    rclone_binary: str = "/usr/bin/rclone"
    rclone_config_path: str = "/etc/ohana-agent/rclone.conf"
    rclone_remote: str = "icloud:Ohana/Backups"
    environment_file: str = "/etc/ohana-agent/backup.env"
    temporary_directory: str = "/run/ohana-agent/backup"
    require_tmpfs: bool = True
    chunk_size_bytes: int = Field(default=1024 * 1024, ge=64 * 1024, le=8 * 1024 * 1024)
    targets: list[BackupTargetPluginConfig] = Field(default_factory=list)
    infra_01: InfraBackupPluginConfig = Field(default_factory=InfraBackupPluginConfig)

    @field_validator(
        "rclone_binary",
        "rclone_config_path",
        "rclone_remote",
        "environment_file",
        "temporary_directory",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Backup plugin paths and remote must not be empty.")
        return normalized

    @field_validator("rclone_remote")
    @classmethod
    def validate_rclone_remote(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        remote_name, separator, remote_path = normalized.partition(":")
        if not separator or not remote_name or not remote_path:
            raise ValueError("rclone_remote must identify a named remote and path.")
        if "/" in remote_name or "\\" in remote_name:
            raise ValueError("rclone_remote must not be a local filesystem path.")
        return normalized

    @model_validator(mode="after")
    def validate_targets(self) -> BackupPluginConfig:
        target_ids = [target.id for target in self.targets]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("Backup target ids must be unique.")
        if self.enabled and not (
            any(target.enabled for target in self.targets) or self.infra_01.enabled
        ):
            raise ValueError(
                "The enabled backup plugin requires at least one target enabled."
            )
        if self.enabled:
            for target in self.targets:
                if not target.enabled:
                    continue
                if not (target.token or target.token_environment_variable):
                    raise ValueError(
                        f"Enabled backup target {target.id} requires a "
                        "Home Assistant token."
                    )
                if not (target.password or target.password_environment_variable):
                    raise ValueError(
                        f"Enabled backup target {target.id} requires an "
                        "encryption password."
                    )
        return self
