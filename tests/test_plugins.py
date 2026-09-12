"""Tests for the Shikamaru plugin manager."""

import pytest

from ohana_agent.core.events import EventBus
from ohana_agent.core.plugins import (
    InvalidPluginStateError,
    Plugin,
    PluginAlreadyRegisteredError,
    PluginInitialized,
    PluginLoaded,
    PluginManager,
    PluginNotRegisteredError,
    PluginStarted,
    PluginState,
    PluginStopped,
    PluginUnloaded,
)
from ohana_agent.core.services import ServiceRegistry


class DummyPlugin(Plugin):
    """Dummy plugin used for tests."""

    def __init__(self, name: str = "dummy") -> None:
        super().__init__(name)
        self.calls: list[str] = []
        self.services: ServiceRegistry | None = None

    def initialize(self, services: ServiceRegistry) -> None:
        """Initialize the dummy plugin."""
        self.calls.append("initialize")
        self.services = services

    def start(self) -> None:
        """Start the dummy plugin."""
        self.calls.append("start")

    def stop(self) -> None:
        """Stop the dummy plugin."""
        self.calls.append("stop")

    def unload(self) -> None:
        """Unload the dummy plugin."""
        self.calls.append("unload")


def create_manager() -> PluginManager:
    """Create a plugin manager for tests."""
    services = ServiceRegistry()
    bus = EventBus()
    return PluginManager(services, bus)


def test_register_plugin() -> None:
    """A plugin can be registered."""
    manager = create_manager()
    plugin = DummyPlugin()

    manager.register(plugin)

    assert manager.get("dummy") is plugin
    assert manager.state("dummy") is PluginState.REGISTERED


def test_register_duplicate_plugin_raises_error() -> None:
    """Registering the same plugin name twice raises an error."""
    manager = create_manager()

    manager.register(DummyPlugin("dummy"))

    with pytest.raises(PluginAlreadyRegisteredError):
        manager.register(DummyPlugin("dummy"))


def test_get_unknown_plugin_raises_error() -> None:
    """Getting an unknown plugin raises an error."""
    manager = create_manager()

    with pytest.raises(PluginNotRegisteredError):
        manager.get("unknown")


def test_initialize_plugin() -> None:
    """A registered plugin can be initialized."""
    services = ServiceRegistry()
    bus = EventBus()
    manager = PluginManager(services, bus)
    plugin = DummyPlugin()

    manager.register(plugin)
    manager.initialize("dummy")

    assert plugin.calls == ["initialize"]
    assert plugin.services is services
    assert manager.state("dummy") is PluginState.INITIALIZED


def test_initialize_plugin_twice_raises_error() -> None:
    """An initialized plugin cannot be initialized again."""
    manager = create_manager()

    manager.register(DummyPlugin())
    manager.initialize("dummy")

    with pytest.raises(InvalidPluginStateError):
        manager.initialize("dummy")


def test_start_plugin() -> None:
    """An initialized plugin can be started."""
    manager = create_manager()
    plugin = DummyPlugin()

    manager.register(plugin)
    manager.initialize("dummy")
    manager.start("dummy")

    assert plugin.calls == ["initialize", "start"]
    assert manager.state("dummy") is PluginState.RUNNING


def test_start_non_initialized_plugin_raises_error() -> None:
    """A non-initialized plugin cannot be started."""
    manager = create_manager()

    manager.register(DummyPlugin())

    with pytest.raises(InvalidPluginStateError):
        manager.start("dummy")


def test_stop_plugin() -> None:
    """A running plugin can be stopped."""
    manager = create_manager()
    plugin = DummyPlugin()

    manager.register(plugin)
    manager.initialize("dummy")
    manager.start("dummy")
    manager.stop("dummy")

    assert plugin.calls == ["initialize", "start", "stop"]
    assert manager.state("dummy") is PluginState.STOPPED


def test_stop_non_running_plugin_raises_error() -> None:
    """A non-running plugin cannot be stopped."""
    manager = create_manager()

    manager.register(DummyPlugin())
    manager.initialize("dummy")

    with pytest.raises(InvalidPluginStateError):
        manager.stop("dummy")


def test_unload_registered_plugin() -> None:
    """A registered plugin can be unloaded and removed."""
    manager = create_manager()
    plugin = DummyPlugin()

    manager.register(plugin)
    manager.unload("dummy")

    assert plugin.calls == ["unload"]

    with pytest.raises(PluginNotRegisteredError):
        manager.get("dummy")


def test_unload_stopped_plugin() -> None:
    """A stopped plugin can be unloaded and removed."""
    manager = create_manager()
    plugin = DummyPlugin()

    manager.register(plugin)
    manager.initialize("dummy")
    manager.start("dummy")
    manager.stop("dummy")
    manager.unload("dummy")

    assert plugin.calls == ["initialize", "start", "stop", "unload"]

    with pytest.raises(PluginNotRegisteredError):
        manager.get("dummy")


def test_unload_running_plugin_raises_error() -> None:
    """A running plugin cannot be unloaded."""
    manager = create_manager()

    manager.register(DummyPlugin())
    manager.initialize("dummy")
    manager.start("dummy")

    with pytest.raises(InvalidPluginStateError):
        manager.unload("dummy")


def test_plugins_returns_copy() -> None:
    """plugins() returns a copy of the registered plugins list."""
    manager = create_manager()

    manager.register(DummyPlugin())

    plugins = manager.plugins()
    plugins.clear()

    assert len(manager.plugins()) == 1


def test_register_publishes_plugin_loaded_event() -> None:
    """Registering a plugin publishes PluginLoaded."""
    services = ServiceRegistry()
    bus = EventBus()
    manager = PluginManager(services, bus)
    received: list[PluginLoaded] = []

    def handler(event: PluginLoaded) -> None:
        received.append(event)

    bus.subscribe(PluginLoaded, handler)

    manager.register(DummyPlugin())

    assert len(received) == 1
    assert received[0].plugin_name == "dummy"


def test_initialize_publishes_plugin_initialized_event() -> None:
    """Initializing a plugin publishes PluginInitialized."""
    services = ServiceRegistry()
    bus = EventBus()
    manager = PluginManager(services, bus)
    received: list[PluginInitialized] = []

    def handler(event: PluginInitialized) -> None:
        received.append(event)

    bus.subscribe(PluginInitialized, handler)

    manager.register(DummyPlugin())
    manager.initialize("dummy")

    assert len(received) == 1
    assert received[0].plugin_name == "dummy"


def test_start_publishes_plugin_started_event() -> None:
    """Starting a plugin publishes PluginStarted."""
    services = ServiceRegistry()
    bus = EventBus()
    manager = PluginManager(services, bus)
    received: list[PluginStarted] = []

    def handler(event: PluginStarted) -> None:
        received.append(event)

    bus.subscribe(PluginStarted, handler)

    manager.register(DummyPlugin())
    manager.initialize("dummy")
    manager.start("dummy")

    assert len(received) == 1
    assert received[0].plugin_name == "dummy"


def test_stop_publishes_plugin_stopped_event() -> None:
    """Stopping a plugin publishes PluginStopped."""
    services = ServiceRegistry()
    bus = EventBus()
    manager = PluginManager(services, bus)
    received: list[PluginStopped] = []

    def handler(event: PluginStopped) -> None:
        received.append(event)

    bus.subscribe(PluginStopped, handler)

    manager.register(DummyPlugin())
    manager.initialize("dummy")
    manager.start("dummy")
    manager.stop("dummy")

    assert len(received) == 1
    assert received[0].plugin_name == "dummy"


def test_unload_publishes_plugin_unloaded_event() -> None:
    """Unloading a plugin publishes PluginUnloaded."""
    services = ServiceRegistry()
    bus = EventBus()
    manager = PluginManager(services, bus)
    received: list[PluginUnloaded] = []

    def handler(event: PluginUnloaded) -> None:
        received.append(event)

    bus.subscribe(PluginUnloaded, handler)

    manager.register(DummyPlugin())
    manager.unload("dummy")

    assert len(received) == 1
    assert received[0].plugin_name == "dummy"
