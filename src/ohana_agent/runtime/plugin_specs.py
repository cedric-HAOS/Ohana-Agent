"""Declarative wiring shared by every production plugin."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ohana_agent.configuration.infrastructure import InfrastructureConfig
from ohana_agent.infrastructure.infrastructure import Infrastructure
from ohana_agent.observation import ObserverResult
from ohana_agent.plugins.administration import PluginAdministrationBinding
from ohana_agent.plugins.runtime.plugin_manager import PluginManager
from ohana_agent.scheduler import Scheduler, Task


def replace_plugin_tasks(
    scheduler: Scheduler,
    tasks: list[Task],
    *,
    plugin_name: str,
) -> None:
    """Atomically replace scheduler tasks managed by one plugin."""
    for task in scheduler.list_tasks():
        if (
            task.command.startswith(f"{plugin_name}.")
            or task.metadata.get("managed_by") == plugin_name
        ):
            scheduler.remove_task(task.id)

    for task in tasks:
        scheduler.add_task(task)


def _reconfigure_plugin(
    plugin: Any,
    config: Any,
    infrastructure_config: InfrastructureConfig | None,
) -> None:
    plugin.reconfigure(config)


@dataclass(frozen=True, slots=True)
class PluginSpec:
    """Everything the production runtime needs to know about one plugin.

    ``build_config`` turns the editable YAML model into the runtime config,
    ``build_tasks`` schedules it, and ``test_plugin`` runs the administration
    self-test against the live plugin instance.
    """

    identifier: str
    display_name: str
    capabilities: tuple[str, ...]
    configuration_model: type[Any]
    load_configuration: Callable[[Path], Any]
    build_config: Callable[[Infrastructure, InfrastructureConfig, Any], Any]
    create_plugin: Callable[[Any], Any]
    build_tasks: Callable[[Any, Any, datetime], list[Task]]
    test_plugin: Callable[[Any], ObserverResult]
    reconfigure: Callable[[Any, Any, InfrastructureConfig | None], None] = (
        _reconfigure_plugin
    )
    follows_infrastructure: bool = True


@dataclass(slots=True)
class ManagedPlugin:
    """One live plugin with its current editable and runtime configuration."""

    spec: PluginSpec
    configuration_path: Path
    plugin_config: Any
    config: Any
    plugin: Any

    @property
    def identifier(self) -> str:
        return self.spec.identifier

    def tasks(self, now: datetime) -> list[Task]:
        """Return the scheduler tasks of this plugin, empty when disabled."""
        return self.tasks_for(self.config, self.plugin_config, now)

    def tasks_for(self, config: Any, plugin_config: Any, now: datetime) -> list[Task]:
        if not plugin_config.enabled:
            return []

        return self.spec.build_tasks(config, plugin_config, now)


class ProductionPlugins:
    """Load, schedule and reconfigure the production plugins as one set."""

    def __init__(
        self,
        plugins: Iterable[ManagedPlugin],
        *,
        infrastructure: Infrastructure,
        infrastructure_config: InfrastructureConfig,
    ) -> None:
        self._plugins = {plugin.identifier: plugin for plugin in plugins}
        self.infrastructure = infrastructure
        self.infrastructure_config = infrastructure_config
        self._on_applied: dict[str, Callable[[Any, Any], None]] = {}

    @classmethod
    def load(
        cls,
        specs: Iterable[PluginSpec],
        configuration_paths: Mapping[str, Path],
        *,
        infrastructure: Infrastructure,
        infrastructure_config: InfrastructureConfig,
    ) -> ProductionPlugins:
        """Read each plugin YAML file and build its live plugin instance."""
        plugins = []

        for spec in specs:
            path = configuration_paths[spec.identifier]
            plugin_config = spec.load_configuration(path)
            config = spec.build_config(
                infrastructure, infrastructure_config, plugin_config
            )
            plugins.append(
                ManagedPlugin(
                    spec=spec,
                    configuration_path=path,
                    plugin_config=plugin_config,
                    config=config,
                    plugin=spec.create_plugin(config),
                )
            )

        return cls(
            plugins,
            infrastructure=infrastructure,
            infrastructure_config=infrastructure_config,
        )

    def __getitem__(self, identifier: str) -> ManagedPlugin:
        return self._plugins[identifier]

    def __iter__(self) -> Iterator[ManagedPlugin]:
        return iter(self._plugins.values())

    def on_applied(
        self,
        identifier: str,
        callback: Callable[[Any, Any], None],
    ) -> None:
        """Call ``callback(config, plugin_config)`` when an edit reconfigures it."""
        self._on_applied[identifier] = callback

    def register(self, plugin_manager: PluginManager) -> None:
        for managed in self:
            plugin_manager.register(managed.plugin)

    def schedule(self, scheduler: Scheduler, now: datetime) -> None:
        for managed in self:
            replace_plugin_tasks(
                scheduler, managed.tasks(now), plugin_name=managed.identifier
            )

    def apply(
        self,
        identifier: str,
        plugin_config: Any,
        *,
        scheduler: Scheduler,
        now: datetime,
    ) -> None:
        """Apply an edited plugin configuration without restarting the agent."""
        managed = self._plugins[identifier]
        config = managed.spec.build_config(
            self.infrastructure, self.infrastructure_config, plugin_config
        )
        managed.spec.reconfigure(managed.plugin, config, None)
        callback = self._on_applied.get(identifier)

        if callback is not None:
            callback(config, plugin_config)

        replace_plugin_tasks(
            scheduler,
            managed.tasks_for(config, plugin_config, now),
            plugin_name=identifier,
        )
        managed.config = config
        managed.plugin_config = plugin_config

    def reconfigure_infrastructure(
        self,
        infrastructure: Infrastructure,
        infrastructure_config: InfrastructureConfig,
        *,
        scheduler: Scheduler,
        now: datetime,
        before_commit: Callable[[], None] = lambda: None,
    ) -> None:
        """Rebuild every infrastructure-dependent plugin, then swap them all.

        Every runtime config and task list is built before anything changes, so
        an invalid infrastructure leaves the running plugins untouched.
        """
        prepared = []

        for managed in self:
            if not managed.spec.follows_infrastructure:
                continue

            config = managed.spec.build_config(
                infrastructure, infrastructure_config, managed.plugin_config
            )
            prepared.append(
                (managed, config, managed.tasks_for(config, managed.plugin_config, now))
            )

        before_commit()

        for managed, config, _ in prepared:
            managed.spec.reconfigure(managed.plugin, config, infrastructure_config)
            managed.config = config

        for managed, _, tasks in prepared:
            replace_plugin_tasks(scheduler, tasks, plugin_name=managed.identifier)

        self.infrastructure = infrastructure
        self.infrastructure_config = infrastructure_config

    def administration_bindings(
        self,
        apply_configuration: Callable[[str, Any], None],
    ) -> tuple[PluginAdministrationBinding, ...]:
        """Expose every plugin to the administration API."""
        return tuple(
            PluginAdministrationBinding(
                identifier=managed.identifier,
                display_name=managed.spec.display_name,
                capabilities=managed.spec.capabilities,
                configuration_path=managed.configuration_path,
                configuration_model=managed.spec.configuration_model,
                apply_configuration=(
                    lambda config, identifier=managed.identifier: apply_configuration(
                        identifier, config
                    )
                ),
                test_plugin=(
                    lambda managed=managed: managed.spec.test_plugin(managed.plugin)
                ),
            )
            for managed in self
        )
