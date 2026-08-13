"""Ohana encrypted backup capability plugin."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from observer.observer_result import ObserverResult
from plugin.plugin import Plugin
from plugin.plugin_context import PluginContext
from plugin.plugin_manifest import PluginManifest
from plugin.plugin_runtime import PluginState
from plugins.backup.backup_config import BackupConfig
from plugins.backup.backup_coordinator import (
    BackupCoordinator,
    BackupExecutionError,
)
from plugins.backup.infra_backup_coordinator import InfraBackupCoordinator


class BackupPlugin(Plugin):
    """Back up HAOS targets and INFRA-01 to an rclone remote."""

    def __init__(
        self,
        *,
        config: BackupConfig | None = None,
        coordinator: BackupCoordinator | None = None,
        infra_coordinator: InfraBackupCoordinator | None = None,
    ) -> None:
        self.config = config or BackupConfig()
        self._coordinator = coordinator or BackupCoordinator(self.config)
        self._infra_coordinator = infra_coordinator or InfraBackupCoordinator(
            self.config
        )
        self._state = PluginState.LOADED

    @property
    def name(self) -> str:
        return "backup"

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name="backup",
            version="0.2.0",
            description="Stream encrypted Ohana backups to off-site storage.",
        )

    def register(self, context: PluginContext) -> None:
        del context
        self._state = PluginState.REGISTERED

    def execute(self, **kwargs: Any) -> ObserverResult:
        target_id = kwargs.get("target_id")
        if not isinstance(target_id, str) or not target_id.strip():
            raise ValueError(
                "BackupPlugin.execute() requires a non-empty 'target_id' argument."
            )
        normalized_target_id = target_id.strip()
        if normalized_target_id == "infra-01":
            return self._execute_infra_backup()
        target = next(
            (item for item in self.config.targets if item.id == normalized_target_id),
            None,
        )
        if target is None:
            raise ValueError(f"Unknown backup target: {target_id!r}.")
        if not target.enabled:
            raise ValueError(f"Backup target is disabled: {target_id!r}.")

        started_at = perf_counter()
        try:
            result = self._coordinator.run(target)
        except BackupExecutionError as error:
            return ObserverResult(
                success=False,
                latency=(perf_counter() - started_at) * 1000,
                message=(
                    f"Backup of {target.label} failed during {error.stage}: {error}"
                ),
                check="backup.run",
                description="Create, upload and rotate one encrypted HAOS backup.",
                metadata=self._metadata(
                    target.id,
                    target.label,
                    stage=error.stage,
                    error=str(error),
                ),
            )

        return ObserverResult(
            success=True,
            latency=(perf_counter() - started_at) * 1000,
            message=(
                f"Backup of {target.label} uploaded and validated; "
                "one managed local backup is retained."
            ),
            check="backup.run",
            description="Create, upload and rotate one encrypted HAOS backup.",
            metadata=self._metadata(
                target.id,
                target.label,
                stage="completed",
                backup_slug=result.backup_slug,
                backup_name=result.backup_name,
                remote_path=result.remote_path,
                size_bytes=result.size_bytes,
                sha256=result.sha256,
                deleted_local_backups=result.deleted_local_backups,
            ),
        )

    def _execute_infra_backup(self) -> ObserverResult:
        if not self.config.infra_01.enabled:
            raise ValueError("Backup target is disabled: 'infra-01'.")
        started_at = perf_counter()
        try:
            result = self._infra_coordinator.run()
        except BackupExecutionError as error:
            return ObserverResult(
                success=False,
                latency=(perf_counter() - started_at) * 1000,
                message=f"Backup of INFRA-01 failed during {error.stage}: {error}",
                check="backup.run",
                description="Create and upload one encrypted INFRA-01 backup.",
                metadata=self._metadata(
                    "infra-01",
                    "INFRA-01",
                    stage=error.stage,
                    error=str(error),
                ),
            )
        return ObserverResult(
            success=True,
            latency=(perf_counter() - started_at) * 1000,
            message="Backup of INFRA-01 uploaded and validated.",
            check="backup.run",
            description="Create and upload one encrypted INFRA-01 backup.",
            metadata=self._metadata(
                "infra-01",
                "INFRA-01",
                stage="completed",
                backup_id=result.backup_id,
                remote_path=result.remote_directory,
                size_bytes=result.size_bytes,
                sha256=result.sha256,
                deleted_remote_backups=result.deleted_remote_backups,
            ),
        )

    def test(self, **kwargs: Any) -> ObserverResult:
        target_id = kwargs.get("target_id")
        targets = [target for target in self.config.targets if target.enabled]
        if isinstance(target_id, str) and target_id.strip():
            targets = [target for target in targets if target.id == target_id.strip()]
        check_infra = self.config.infra_01.enabled and (
            not isinstance(target_id, str)
            or not target_id.strip()
            or target_id == "infra-01"
        )
        if not targets and not check_infra:
            raise ValueError("The backup plugin has no enabled HAOS target.")

        started_at = perf_counter()
        checked = 0
        backup_count = 0
        try:
            for target in targets:
                backup_count += self._coordinator.preflight(target)
                checked += 1
            if check_infra:
                self._infra_coordinator.preflight()
                checked += 1
        except BackupExecutionError as error:
            return ObserverResult(
                success=False,
                latency=(perf_counter() - started_at) * 1000,
                message=f"Backup preflight failed during {error.stage}: {error}",
                check="backup.preflight",
                description="Validate HAOS and iCloud backup access without writing.",
                metadata={
                    "stage": error.stage,
                    "checked_targets": checked,
                    "error": str(error),
                },
            )

        return ObserverResult(
            success=True,
            latency=(perf_counter() - started_at) * 1000,
            message=(
                f"Backup configuration validated for {checked} target(s); "
                "no backup was created."
            ),
            check="backup.preflight",
            description="Validate HAOS and iCloud backup access without writing.",
            metadata={
                "stage": "validated",
                "checked_targets": checked,
                "local_backup_count": backup_count,
            },
        )

    def reconfigure(self, config: BackupConfig) -> None:
        """Apply an updated policy without restarting Agent."""
        self.config = config
        self._coordinator = BackupCoordinator(config)
        self._infra_coordinator = InfraBackupCoordinator(config)

    @staticmethod
    def _metadata(
        target_id: str,
        label: str,
        **metadata: object,
    ) -> dict[str, object]:
        return {
            "target_type": "device",
            "device_id": target_id,
            "node_id": target_id,
            "device_label": label,
            **metadata,
        }
