from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ohana_agent.runtime.plugin_specs import (
    PluginSpec,
    ProductionPlugins,
    replace_plugin_tasks,
)
from ohana_agent.scheduler import IntervalTrigger, Task

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class FakePluginConfig:
    services: tuple[str, ...]
    enabled: bool = True


@dataclass
class FakePlugin:
    config: tuple[str, ...]
    reconfigured: list[tuple[tuple[str, ...], object]] = field(default_factory=list)

    def reconfigure(self, config, infrastructure=None) -> None:
        self.config = config
        self.reconfigured.append((config, infrastructure))


class FakeScheduler:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}

    def list_tasks(self) -> list[Task]:
        return list(self.tasks.values())

    def add_task(self, task: Task) -> None:
        self.tasks[task.id] = task

    def remove_task(self, task_id: str) -> None:
        del self.tasks[task_id]


def _task(identifier: str, name: str) -> Task:
    return Task(
        id=f"{identifier}.check:{name}",
        name=name,
        command=f"{identifier}.check",
        trigger=IntervalTrigger(interval=timedelta(seconds=60), start_at=NOW),
        metadata={"managed_by": identifier},
    )


def _spec(identifier: str, *, follows_infrastructure: bool = True) -> PluginSpec:
    def build_config(infrastructure, _, plugin_config):
        if "invalid" in infrastructure:
            raise ValueError(f"{identifier} rejects the infrastructure")
        return tuple(f"{infrastructure}/{name}" for name in plugin_config.services)

    return PluginSpec(
        identifier=identifier,
        display_name=identifier.upper(),
        capabilities=(f"{identifier}.check",),
        configuration_model=FakePluginConfig,
        load_configuration=lambda path: FakePluginConfig(services=(path.stem,)),
        build_config=build_config,
        create_plugin=FakePlugin,
        build_tasks=lambda config, _, __: [_task(identifier, name) for name in config],
        test_plugin=lambda plugin: plugin.config,
        reconfigure=lambda plugin, config, infrastructure: plugin.reconfigure(
            config, infrastructure
        ),
        follows_infrastructure=follows_infrastructure,
    )


def _plugins() -> ProductionPlugins:
    return ProductionPlugins.load(
        (_spec("alpha"), _spec("beta", follows_infrastructure=False)),
        {"alpha": Path("a.yaml"), "beta": Path("b.yaml")},
        infrastructure="infra-1",
        infrastructure_config="config-1",
    )


def test_load_builds_each_plugin_from_its_configuration_file() -> None:
    plugins = _plugins()

    assert [managed.identifier for managed in plugins] == ["alpha", "beta"]
    assert plugins["alpha"].plugin.config == ("infra-1/a",)
    assert plugins["beta"].configuration_path == Path("b.yaml")


def test_schedule_skips_disabled_plugins() -> None:
    plugins = _plugins()
    plugins["beta"].plugin_config = FakePluginConfig(services=("b",), enabled=False)
    scheduler = FakeScheduler()

    plugins.schedule(scheduler, NOW)

    assert list(scheduler.tasks) == ["alpha.check:infra-1/a"]


def test_apply_reconfigures_one_plugin_and_replaces_only_its_tasks() -> None:
    plugins = _plugins()
    scheduler = FakeScheduler()
    plugins.schedule(scheduler, NOW)
    applied = []
    plugins.on_applied("alpha", lambda config, _: applied.append(config))

    plugins.apply(
        "alpha",
        FakePluginConfig(services=("x", "y")),
        scheduler=scheduler,
        now=NOW,
    )

    assert plugins["alpha"].plugin.reconfigured == [(("infra-1/x", "infra-1/y"), None)]
    assert plugins["alpha"].plugin_config.services == ("x", "y")
    assert applied == [("infra-1/x", "infra-1/y")]
    assert sorted(scheduler.tasks) == [
        "alpha.check:infra-1/x",
        "alpha.check:infra-1/y",
        "beta.check:infra-1/b",
    ]


def test_infrastructure_change_rebuilds_only_dependent_plugins() -> None:
    plugins = _plugins()
    scheduler = FakeScheduler()
    plugins.schedule(scheduler, NOW)
    committed = []

    plugins.reconfigure_infrastructure(
        "infra-2",
        "config-2",
        scheduler=scheduler,
        now=NOW,
        before_commit=lambda: committed.append(True),
    )

    assert committed == [True]
    assert plugins["alpha"].plugin.reconfigured == [(("infra-2/a",), "config-2")]
    assert plugins["beta"].plugin.reconfigured == []
    assert sorted(scheduler.tasks) == ["alpha.check:infra-2/a", "beta.check:infra-1/b"]
    assert plugins.infrastructure_config == "config-2"


def test_rejected_infrastructure_leaves_running_plugins_untouched() -> None:
    plugins = _plugins()
    scheduler = FakeScheduler()
    plugins.schedule(scheduler, NOW)

    with pytest.raises(ValueError, match="alpha rejects"):
        plugins.reconfigure_infrastructure(
            "invalid",
            "config-2",
            scheduler=scheduler,
            now=NOW,
            before_commit=pytest.fail,
        )

    assert plugins["alpha"].plugin.reconfigured == []
    assert plugins.infrastructure == "infra-1"
    assert "alpha.check:infra-1/a" in scheduler.tasks


def test_administration_bindings_route_to_the_matching_plugin() -> None:
    plugins = _plugins()
    calls = []

    bindings = plugins.administration_bindings(
        lambda identifier, config: calls.append((identifier, config))
    )
    bindings[1].apply_configuration("new-beta")

    assert [binding.identifier for binding in bindings] == ["alpha", "beta"]
    assert bindings[0].capabilities == ("alpha.check",)
    assert bindings[0].test_plugin() == ("infra-1/a",)
    assert calls == [("beta", "new-beta")]


def test_replace_plugin_tasks_matches_command_prefix_and_owner() -> None:
    scheduler = FakeScheduler()
    scheduler.add_task(_task("alpha", "old"))
    scheduler.add_task(_task("beta", "kept"))

    replace_plugin_tasks(scheduler, [_task("alpha", "new")], plugin_name="alpha")

    assert sorted(scheduler.tasks) == ["alpha.check:new", "beta.check:kept"]
