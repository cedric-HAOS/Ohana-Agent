from pathlib import Path

import pytest

from ohana_agent.observation import ObserverResult
from ohana_agent.plugins.dns.plugin import DNSPlugin
from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_context import PluginContext
from ohana_agent.plugins.runtime.plugin_descriptor import PluginDescriptor
from ohana_agent.plugins.runtime.plugin_errors import PluginNotFoundError
from ohana_agent.plugins.runtime.plugin_events import (
    PluginRegistered,
    PluginUnregistered,
)
from ohana_agent.plugins.runtime.plugin_manager import PluginManager
from ohana_agent.plugins.runtime.plugin_manifest import PluginManifest
from ohana_agent.plugins.runtime.plugin_state import PluginState


class FakeEventBus:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event: object) -> None:
        self.events.append(event)


class FakePlugin(Plugin):
    def __init__(self, name: str) -> None:
        self._manifest = PluginManifest(
            name=name,
            version="1.0.0",
        )
        self.registered_context: PluginContext | None = None

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    def register(self, context: PluginContext) -> None:
        self.registered_context = context

    def execute(self, **kwargs: object) -> ObserverResult:
        """Execute the fake plugin."""
        return ObserverResult(
            success=True,
            latency=0.0,
            check="test",
        )


class FakeDiscovery:
    def __init__(self, descriptors) -> None:
        self._descriptors = descriptors

    def discover(self):
        return self._descriptors


class FakeLoader:
    def __init__(self, plugins) -> None:
        self._plugins = plugins
        self.loaded_descriptors = None

    def load_all(self, descriptors):
        self.loaded_descriptors = descriptors
        return self._plugins


def make_context(event_bus=None) -> PluginContext:
    return PluginContext(
        event_bus=event_bus or FakeEventBus(),
        scheduler=object(),
        dispatcher=object(),
        memory=object(),
        capability_manager=object(),
        configuration=object(),
        runtime=object(),
    )


def test_plugin_manager_discovers_plugins() -> None:
    descriptor = PluginDescriptor(
        name="dns",
        path=Path("plugins/dns"),
    )

    manager = PluginManager(
        context=make_context(),
        discovery=FakeDiscovery((descriptor,)),
    )

    descriptors = manager.discover()

    assert descriptors == (descriptor,)
    assert manager.runtime.state("dns") == PluginState.DISCOVERED


def test_plugin_manager_loads_plugins() -> None:
    descriptor = PluginDescriptor(
        name="dns",
        path=Path("plugins/dns"),
    )
    plugin = FakePlugin("dns")
    loader = FakeLoader((plugin,))

    manager = PluginManager(
        context=make_context(),
        loader=loader,
    )

    plugins = manager.load((descriptor,))

    assert plugins == (plugin,)
    assert loader.loaded_descriptors == (descriptor,)
    assert manager.runtime.state("dns") == PluginState.LOADED


def test_plugin_manager_registers_plugin() -> None:
    event_bus = FakeEventBus()
    context = make_context(event_bus)
    plugin = FakePlugin("dns")

    manager = PluginManager(context=context)

    manager.register(plugin)

    assert manager.count == 1
    assert manager.get("dns") is plugin
    assert plugin.registered_context is context
    assert manager.runtime.state("dns") == PluginState.REGISTERED
    assert isinstance(event_bus.events[0], PluginRegistered)


def test_plugin_manager_unregisters_plugin() -> None:
    event_bus = FakeEventBus()
    plugin = FakePlugin("dns")

    manager = PluginManager(context=make_context(event_bus))

    manager.register(plugin)
    manager.unregister("dns")

    assert manager.count == 0
    assert manager.runtime.state("dns") == PluginState.UNLOADED
    assert isinstance(event_bus.events[-1], PluginUnregistered)


def test_plugin_manager_unregister_unknown_plugin_raises() -> None:
    manager = PluginManager(context=make_context())

    with pytest.raises(PluginNotFoundError):
        manager.unregister("unknown")


def test_plugin_manager_start_runs_full_pipeline() -> None:
    descriptor = PluginDescriptor(
        name="dns",
        path=Path("plugins/dns"),
    )
    plugin = FakePlugin("dns")

    manager = PluginManager(
        context=make_context(),
        discovery=FakeDiscovery((descriptor,)),
        loader=FakeLoader((plugin,)),
    )

    plugins = manager.start()

    assert plugins == (plugin,)
    assert manager.has("dns") is True
    assert manager.runtime.state("dns") == PluginState.REGISTERED


def test_plugin_manager_registers_dns_plugin() -> None:
    event_bus = FakeEventBus()
    context = make_context(event_bus)
    plugin = DNSPlugin()
    manager = PluginManager(context=context)

    manager.register(plugin)

    assert manager.count == 1
    assert manager.get("dns") is plugin
    assert manager.has("dns") is True
    assert plugin.state is PluginState.REGISTERED
    assert manager.runtime.get_state("dns") is PluginState.REGISTERED
    assert plugin.manifest.name == "dns"
    assert plugin._event_bus is event_bus
    assert isinstance(event_bus.events[-1], PluginRegistered)
