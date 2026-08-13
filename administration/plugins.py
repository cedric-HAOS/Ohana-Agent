"""Administration of the plugins registered in Ohana-Agent."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, Thread
from types import SimpleNamespace
from typing import Any

import yaml
from pydantic import BaseModel

from administration.models import (
    PluginAdministrationCollection,
    PluginAdministrationState,
    PluginConfigurationUpdate,
    PluginTestResult,
)
from observer.observer_result import ObserverResult
from plugin.plugin_manager import PluginManager
from plugin.plugin_state import PluginState
from plugins.backup.backup_secrets import resolve_backup_secret
from plugins.backup.rclone_icloud import RcloneICloudConfigurator
from scheduler import Scheduler, Task

LOGGER = logging.getLogger(__name__)

PLUGIN_IDENTIFIER_ALIASES = {
    "shelly_telemetry": "home_assistant_telemetry",
}


@dataclass(frozen=True, slots=True)
class PluginAdministrationBinding:
    """Connect one registered plugin to its editable configuration."""

    identifier: str
    display_name: str
    capabilities: tuple[str, ...]
    configuration_path: Path
    configuration_model: type[BaseModel]
    apply_configuration: Callable[[BaseModel], None]
    test_plugin: Callable[[], ObserverResult]


class PluginAdministrationRepository:
    """Read, persist, reconfigure and test registered plugins."""

    def __init__(
        self,
        *,
        plugin_manager: PluginManager,
        scheduler: Scheduler,
        bindings: tuple[PluginAdministrationBinding, ...],
        icloud_configurator: RcloneICloudConfigurator | None = None,
        backup_runner: Callable[[dict[str, object]], object] | None = None,
    ) -> None:
        self.plugin_manager = plugin_manager
        self.scheduler = scheduler
        self.bindings = {binding.identifier: binding for binding in bindings}
        self._icloud_configurator = icloud_configurator
        self._backup_runner = backup_runner
        self._running_backup_targets: set[str] = set()
        self._backup_run_lock = Lock()

    def list(self) -> PluginAdministrationCollection:
        """Return all administrable plugins ordered by display name."""
        plugins = [self.read(identifier) for identifier in self.bindings]
        plugins.sort(key=lambda plugin: plugin.name.casefold())
        return PluginAdministrationCollection(plugins=plugins)

    def read(self, identifier: str) -> PluginAdministrationState:
        """Return the current configuration and runtime state of one plugin."""
        identifier = self._canonical_identifier(identifier)
        binding = self._binding(identifier)
        plugin = self._plugin(identifier)
        configuration = self._read_configuration(binding)
        tasks = self._tasks(identifier)
        enabled = bool(getattr(configuration, "enabled", True))
        last_failed_task = self._last_failed_task(tasks)
        lifecycle_state = self.plugin_manager.runtime.get_state(identifier)

        return PluginAdministrationState(
            id=identifier,
            name=binding.display_name,
            description=plugin.manifest.description,
            version=plugin.manifest.version,
            lifecycle_state=(
                lifecycle_state.value
                if lifecycle_state is not None
                else PluginState.REGISTERED.value
            ),
            status=self._status(
                enabled=enabled,
                tasks=tasks,
                last_failed_task=last_failed_task,
            ),
            enabled=enabled,
            capabilities=list(binding.capabilities),
            interval_seconds=int(getattr(configuration, "interval_seconds", 0)),
            task_count=len(tasks),
            execution_count=sum(task.execution_count for task in tasks),
            last_execution_at=self._last_execution(tasks),
            next_run_at=self._next_run(tasks),
            last_error=(
                last_failed_task.last_error if last_failed_task is not None else None
            ),
            configuration=self._public_configuration(
                identifier,
                configuration,
            ),
        )

    def write(
        self,
        identifier: str,
        payload: dict[str, Any],
    ) -> PluginAdministrationState:
        """Validate, persist and immediately apply a plugin configuration."""
        identifier = self._canonical_identifier(identifier)
        binding = self._binding(identifier)
        update = PluginConfigurationUpdate.model_validate(payload)
        current_configuration = self._read_configuration(binding)
        configuration_payload = dict(update.configuration)
        configuration_payload["enabled"] = update.enabled

        if identifier == "backup":
            self._strip_backup_runtime_status(configuration_payload)
            self._preserve_backup_secrets(
                configuration_payload,
                current_configuration,
            )
        elif identifier == "mqtt":
            self._preserve_mqtt_password(
                configuration_payload,
                current_configuration,
            )
        elif identifier == "wireguard":
            self._preserve_secret(
                configuration_payload,
                current_configuration,
                field_name="app_token",
            )
        elif identifier == "home_assistant_telemetry":
            self._preserve_secret(
                configuration_payload,
                current_configuration,
                field_name="access_token",
            )
        elif identifier == "teleinformation":
            self._preserve_secret(
                configuration_payload,
                current_configuration,
                field_name="access_token",
            )
            self._preserve_secret(
                configuration_payload,
                current_configuration,
                field_name="ingestion_token",
            )
        configuration = binding.configuration_model.model_validate(
            configuration_payload
        )

        if (
            identifier == "dns"
            and bool(getattr(configuration, "enabled", True))
            and not getattr(configuration, "queries", [])
        ):
            raise ValueError("An enabled DNS plugin must declare at least one query.")

        original_content = binding.configuration_path.read_text(encoding="utf-8")
        self._write_configuration(
            binding.configuration_path,
            configuration,
        )
        if identifier == "backup":
            binding.configuration_path.chmod(0o600)

        try:
            binding.apply_configuration(configuration)
        except Exception:
            LOGGER.exception(
                "Plugin reconfiguration failed for %s; "
                "restoring previous configuration",
                identifier,
            )
            self._write_text(binding.configuration_path, original_content)
            if identifier == "backup":
                binding.configuration_path.chmod(0o600)

            try:
                binding.apply_configuration(current_configuration)
            except Exception:
                LOGGER.exception(
                    "Unable to restore runtime configuration for plugin %s",
                    identifier,
                )

            raise

        return self.read(identifier)

    def test(self, identifier: str) -> PluginTestResult:
        """Execute one immediate check with the current plugin configuration."""
        identifier = self._canonical_identifier(identifier)
        binding = self._binding(identifier)
        self._plugin(identifier)
        result = binding.test_plugin()
        return PluginTestResult(
            plugin_id=identifier,
            success=result.success,
            check=result.check,
            message=result.message,
            latency_ms=result.latency,
            tested_at=result.timestamp,
            metadata=result.metadata,
        )

    def connect_backup_icloud(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Start or complete the rclone iCloud authentication flow."""
        configurator = self._backup_icloud_configurator()
        return configurator.connect(
            apple_id=payload.get("apple_id"),
            password=payload.get("password"),
            two_factor_code=payload.get("two_factor_code"),
        )

    def run_backup(self, target_id: str) -> dict[str, object]:
        """Start one enabled HAOS backup without blocking administration."""
        normalized_target_id = target_id.strip()
        if not normalized_target_id:
            raise ValueError("Backup target id cannot be empty.")
        if self._backup_runner is None:
            raise LookupError("Manual HAOS backup is unavailable")

        binding = self._binding("backup")
        self._plugin("backup")
        configuration = self._read_configuration(binding)
        if not bool(getattr(configuration, "enabled", False)):
            raise ValueError("The HAOS backup plugin is disabled.")

        target = next(
            (
                item
                for item in getattr(configuration, "targets", [])
                if item.id == normalized_target_id
            ),
            None,
        )
        if target is None and normalized_target_id == "infra-01":
            infra = getattr(configuration, "infra_01", None)
            if infra is not None and infra.enabled:
                target = SimpleNamespace(id="infra-01", label="INFRA-01", enabled=True)
        if target is None:
            raise LookupError(f"Unknown backup target: {normalized_target_id}")
        if not target.enabled:
            raise ValueError(f"Backup target is disabled: {normalized_target_id}")

        with self._backup_run_lock:
            if normalized_target_id in self._running_backup_targets:
                raise ValueError(
                    f"A backup is already running for {normalized_target_id}."
                )
            self._running_backup_targets.add(normalized_target_id)

        arguments: dict[str, object] = {
            "target_id": normalized_target_id,
            "device_id": normalized_target_id,
            "node_id": normalized_target_id,
        }
        Thread(
            target=self._run_backup_in_background,
            args=(normalized_target_id, arguments),
            name=f"ohana-backup-{normalized_target_id}",
            daemon=True,
        ).start()
        return {
            "schema_version": 1,
            "target_id": normalized_target_id,
            "status": "accepted",
            "message": f"Backup started for {target.label}.",
        }

    def _run_backup_in_background(
        self,
        target_id: str,
        arguments: dict[str, object],
    ) -> None:
        try:
            assert self._backup_runner is not None
            self._backup_runner(arguments)
        except Exception:
            LOGGER.exception("Manual HAOS backup failed for %s", target_id)
        finally:
            with self._backup_run_lock:
                self._running_backup_targets.discard(target_id)

    def _backup_icloud_configurator(self) -> RcloneICloudConfigurator:
        if self._icloud_configurator is not None:
            return self._icloud_configurator
        binding = self._binding("backup")
        configuration = self._read_configuration(binding)
        remote_name = str(configuration.rclone_remote).partition(":")[0]
        self._icloud_configurator = RcloneICloudConfigurator(
            binary=str(configuration.rclone_binary),
            config_path=str(configuration.rclone_config_path),
            remote_name=remote_name,
        )
        return self._icloud_configurator

    @staticmethod
    def _canonical_identifier(identifier: str) -> str:
        """Resolve identifiers retained for backward compatibility."""
        return PLUGIN_IDENTIFIER_ALIASES.get(identifier, identifier)

    def _binding(self, identifier: str) -> PluginAdministrationBinding:
        binding = self.bindings.get(identifier)

        if binding is None:
            raise LookupError(f"Plugin administration is unavailable: {identifier}")

        return binding

    def _plugin(self, identifier: str) -> Any:
        if not self.plugin_manager.has(identifier):
            raise LookupError(f"Plugin is not registered: {identifier}")

        return self.plugin_manager.get(identifier)

    def _read_configuration(
        self,
        binding: PluginAdministrationBinding,
    ) -> BaseModel:
        try:
            payload = (
                yaml.safe_load(binding.configuration_path.read_text(encoding="utf-8"))
                or {}
            )
        except OSError as error:
            raise OSError(
                "Unable to read plugin configuration "
                f"{binding.configuration_path}: {error}"
            ) from error

        return binding.configuration_model.model_validate(payload)

    @classmethod
    def _write_configuration(
        cls,
        path: Path,
        configuration: BaseModel,
    ) -> None:
        payload = configuration.model_dump(
            mode="json",
            exclude_none=False,
        )
        content = yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
        )
        cls._write_text(path, content)

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        temporary_path: Path | None = None
        existing_mode = path.stat().st_mode if path.exists() else None

        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_path = Path(temporary_file.name)

            if existing_mode is not None:
                temporary_path.chmod(existing_mode)

            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _tasks(self, identifier: str) -> list[Task]:
        return [
            task
            for task in self.scheduler.list_tasks()
            if (
                task.command.startswith(f"{identifier}.")
                or task.metadata.get("managed_by") == identifier
            )
        ]

    @staticmethod
    def _last_execution(tasks: list[Task]) -> Any:
        executions = [
            task.last_execution for task in tasks if task.last_execution is not None
        ]
        return max(executions, default=None)

    def _next_run(self, tasks: list[Task]) -> Any:
        now = self.scheduler.clock.now()
        executions = []

        for task in tasks:
            next_run = task.next_run_at(now)

            if next_run is not None:
                executions.append(next_run)

        return min(executions, default=None)

    @staticmethod
    def _last_failed_task(tasks: list[Task]) -> Task | None:
        failed_tasks = [
            task
            for task in tasks
            if task.last_failed_at is not None and task.last_error
        ]

        if not failed_tasks:
            return None

        return max(failed_tasks, key=lambda task: task.last_failed_at)

    @staticmethod
    def _status(
        *,
        enabled: bool,
        tasks: list[Task],
        last_failed_task: Task | None,
    ) -> str:
        if not enabled:
            return "disabled"

        if last_failed_task is not None:
            return "degraded"

        if not tasks:
            return "idle"

        return "active"

    def _public_configuration(
        self,
        identifier: str,
        configuration: BaseModel,
    ) -> dict[str, Any]:
        payload = configuration.model_dump(
            mode="json",
            exclude={"enabled"},
            exclude_none=False,
        )

        if identifier == "mqtt":
            authentication = payload.get("authentication")

            if isinstance(authentication, dict):
                password = authentication.get("password")
                authentication["password_configured"] = bool(password)
                authentication["password"] = None
        elif identifier == "wireguard":
            PluginAdministrationRepository._mask_secret(
                payload,
                field_name="app_token",
            )
        elif identifier == "home_assistant_telemetry":
            PluginAdministrationRepository._mask_secret(
                payload,
                field_name="access_token",
            )
        elif identifier == "teleinformation":
            PluginAdministrationRepository._mask_secret(
                payload,
                field_name="access_token",
            )
            PluginAdministrationRepository._mask_secret(
                payload,
                field_name="ingestion_token",
            )
        elif identifier == "backup":
            targets = payload.get("targets", [])
            environment_file = str(getattr(configuration, "environment_file", ""))
            with self._backup_run_lock:
                running_target_ids = set(self._running_backup_targets)
            if isinstance(targets, list):
                for target in targets:
                    if not isinstance(target, dict):
                        continue
                    target["backup_in_progress"] = (
                        target.get("id") in running_target_ids
                    )
                    token_name = target.get("token_environment_variable")
                    password_name = target.get("password_environment_variable")
                    try:
                        target["token_configured"] = bool(
                            target.get("token")
                            or (
                                isinstance(token_name, str)
                                and resolve_backup_secret(environment_file, token_name)
                            )
                        )
                        target["password_configured"] = bool(
                            target.get("password")
                            or (
                                isinstance(password_name, str)
                                and resolve_backup_secret(
                                    environment_file, password_name
                                )
                            )
                        )
                    except OSError:
                        target["token_configured"] = False
                        target["password_configured"] = False
                    target["token"] = None
                    target["password"] = None
            payload["icloud"] = self._backup_icloud_configurator().status()
            infra = payload.get("infra_01")
            if isinstance(infra, dict):
                infra["backup_in_progress"] = "infra-01" in running_target_ids

        return payload

    @staticmethod
    def _strip_backup_runtime_status(payload: dict[str, Any]) -> None:
        payload.pop("icloud", None)
        infra = payload.get("infra_01")
        if isinstance(infra, dict):
            infra.pop("backup_in_progress", None)
        targets = payload.get("targets", [])
        if not isinstance(targets, list):
            return
        for target in targets:
            if isinstance(target, dict):
                target.pop("token_configured", None)
                target.pop("password_configured", None)
                target.pop("backup_in_progress", None)

    @staticmethod
    def _preserve_backup_secrets(
        payload: dict[str, Any],
        current_configuration: BaseModel,
    ) -> None:
        targets = payload.get("targets", [])
        current_targets = {
            target.id: target
            for target in getattr(current_configuration, "targets", [])
        }
        if not isinstance(targets, list):
            return
        for target in targets:
            if not isinstance(target, dict):
                continue
            current = current_targets.get(target.get("id"))
            for field_name in ("token", "password"):
                if target.get(field_name) not in (None, ""):
                    continue
                target[field_name] = getattr(current, field_name, None)

    @staticmethod
    def _mask_secret(
        payload: dict[str, Any],
        *,
        field_name: str,
    ) -> None:
        secret = payload.get(field_name)
        payload[f"{field_name}_configured"] = bool(secret)
        payload[field_name] = None

    @staticmethod
    def _preserve_secret(
        payload: dict[str, Any],
        current_configuration: BaseModel,
        *,
        field_name: str,
    ) -> None:
        secret = payload.get(field_name)

        if secret not in (None, ""):
            payload.pop(f"{field_name}_configured", None)
            return

        payload[field_name] = getattr(
            current_configuration,
            field_name,
            None,
        )
        payload.pop(f"{field_name}_configured", None)

    @staticmethod
    def _preserve_mqtt_password(
        payload: dict[str, Any],
        current_configuration: BaseModel,
    ) -> None:
        authentication = payload.setdefault("authentication", {})

        if not isinstance(authentication, dict):
            return

        password = authentication.get("password")

        if password not in (None, ""):
            authentication.pop("password_configured", None)
            return

        current_authentication = getattr(
            current_configuration,
            "authentication",
            None,
        )
        current_password = getattr(
            current_authentication,
            "password",
            None,
        )
        authentication["password"] = current_password
        authentication.pop("password_configured", None)
