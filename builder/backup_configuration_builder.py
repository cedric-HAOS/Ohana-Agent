"""Build runtime HAOS backup configuration."""

from configuration.backup import BackupPluginConfig
from plugins.backup.backup_config import (
    BackupAction,
    BackupConfig,
    BackupTarget,
    InfraBackupConfig,
)


class BackupConfigurationBuilder:
    """Convert validated plugin configuration into runtime values."""

    def build(self, config: BackupPluginConfig) -> BackupConfig:
        return BackupConfig(
            targets=tuple(
                BackupTarget(
                    id=target.id,
                    label=target.label,
                    enabled=target.enabled,
                    url=target.url,
                    token=target.token,
                    password=target.password,
                    token_environment_variable=target.token_environment_variable,
                    password_environment_variable=(
                        target.password_environment_variable
                    ),
                    schedule=target.schedule,
                    verify_tls=target.verify_tls,
                    timeout=target.timeout,
                    pre_backup_action=(
                        BackupAction(
                            domain=target.pre_backup_action.domain,
                            service=target.pre_backup_action.service,
                            data=target.pre_backup_action.data.copy(),
                        )
                        if target.pre_backup_action is not None
                        else None
                    ),
                )
                for target in config.targets
            ),
            rclone_binary=config.rclone_binary,
            rclone_config_path=config.rclone_config_path,
            rclone_remote=config.rclone_remote.rstrip("/"),
            environment_file=config.environment_file,
            temporary_directory=config.temporary_directory,
            require_tmpfs=config.require_tmpfs,
            chunk_size_bytes=config.chunk_size_bytes,
            infra_01=InfraBackupConfig(
                enabled=config.infra_01.enabled,
                schedule=config.infra_01.schedule,
                age_binary=config.infra_01.age_binary,
                age_recipient=config.infra_01.age_recipient,
                age_recipient_file=config.infra_01.age_recipient_file,
                age_identity_file=config.infra_01.age_identity_file,
                recovery_remote_path=config.infra_01.recovery_remote_path,
                remote_retention_count=config.infra_01.remote_retention_count,
            ),
        )
