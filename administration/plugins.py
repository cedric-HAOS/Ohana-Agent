"""Administration of the plugins registered in Ohana-Agent."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
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
from scheduler import Scheduler, Task

LOGGER = logging.getLogger(__name__)


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
    ) -> None:
        self.plugin_manager = plugin_manager
        self.scheduler = scheduler
        self.bindings = {binding.identifier: binding for binding in bindings}

    def list(self) -> PluginAdministrationCollection:
        """Return all administrable plugins ordered by display name."""
        plugins = [self.read(identifier) for identifier in self.bindings]
        plugins.sort(key=lambda plugin: plugin.name.casefold())
        return PluginAdministrationCollection(plugins=plugins)

    def read(self, identifier: str) -> PluginAdministrationState:
        """Return the current configuration and runtime state of one plugin."""
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
        binding = self._binding(identifier)
        update = PluginConfigurationUpdate.model_validate(payload)
        current_configuration = self._read_configuration(binding)
        configuration_payload = dict(update.configuration)
        configuration_payload["enabled"] = update.enabled

        if identifier == "mqtt":
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
        elif identifier == "shelly_telemetry":
            self._preserve_secret(
                configuration_payload,
                current_configuration,
                field_name="access_token",
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

        try:
            binding.apply_configuration(configuration)
        except Exception:
            LOGGER.exception(
                "Plugin reconfiguration failed for %s; "
                "restoring previous configuration",
                identifier,
            )
            self._write_text(binding.configuration_path, original_content)

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

    @staticmethod
    def _public_configuration(
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
        elif identifier == "shelly_telemetry":
            PluginAdministrationRepository._mask_secret(
                payload,
                field_name="access_token",
            )

        return payload

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
