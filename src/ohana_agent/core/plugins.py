"""Plugin lifecycle management for Shikamaru."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from ohana_agent.core.capability.base import BaseCapability
from ohana_agent.core.capability.capability_manager import CapabilityManager
from ohana_agent.core.event import Event
from ohana_agent.core.services import ServiceRegistry


class PluginState(Enum):
    """Possible plugin lifecycle states."""

    REGISTERED = auto()
    INITIALIZED = auto()
    RUNNING = auto()
    STOPPED = auto()


class PluginError(Exception):
    """Base exception for plugin errors."""


class PluginAlreadyRegisteredError(PluginError):
    """Raised when a plugin is already registered."""


class PluginNotRegisteredError(PluginError):
    """Raised when a plugin is not registered."""


class InvalidPluginStateError(PluginError):
    """Raised when a plugin lifecycle transition is invalid."""


@dataclass(slots=True)
class PluginLoaded(Event):
    """Event published when a plugin is loaded."""

    plugin_name: str = ""


@dataclass(slots=True)
class PluginInitialized(Event):
    """Event published when a plugin is initialized."""

    plugin_name: str = ""


@dataclass(slots=True)
class PluginStarted(Event):
    """Event published when a plugin is started."""

    plugin_name: str = ""


@dataclass(slots=True)
class PluginStopped(Event):
    """Event published when a plugin is stopped."""

    plugin_name: str = ""


@dataclass(slots=True)
class PluginUnloaded(Event):
    """Event published when a plugin is unloaded."""

    plugin_name: str = ""


class Plugin(ABC):
    """Base class for all Shikamaru plugins."""

    name: str

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def initialize(self, services: ServiceRegistry) -> None:
        """Initialize the plugin with core services."""

    @abstractmethod
    def start(self) -> None:
        """Start the plugin."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the plugin."""

    @abstractmethod
    def unload(self) -> None:
        """Unload the plugin."""


@dataclass(slots=True)
class RegisteredPlugin:
    """Plugin registered with its lifecycle state."""

    plugin: Plugin
    state: PluginState


class PluginManager:
    """Manage plugin registration and lifecycle."""

    def __init__(
        self,
        services: ServiceRegistry,
        event_bus: Any,
        capability_manager: CapabilityManager | None = None,
    ) -> None:
        self._services = services
        self._event_bus = event_bus
        self._plugins: dict[str, RegisteredPlugin] = {}
        self._capability_manager = capability_manager

    def register_plugin_capabilities(self, plugin: Any) -> list[BaseCapability]:
        """Register capabilities exposed by a plugin."""
        if self._capability_manager is None:
            return []

        capabilities_method = getattr(plugin, "capabilities", None)

        if capabilities_method is None:
            return []

        capabilities = capabilities_method()

        for capability in capabilities:
            self._capability_manager.register(capability)

        return capabilities

    def register(self, plugin: Plugin) -> None:
        """Register a plugin."""
        if plugin.name in self._plugins:
            raise PluginAlreadyRegisteredError(
                f"Plugin already registered: {plugin.name}"
            )

        self._plugins[plugin.name] = RegisteredPlugin(
            plugin=plugin,
            state=PluginState.REGISTERED,
        )

        self.register_plugin_capabilities(plugin)
        self._event_bus.publish(PluginLoaded(plugin_name=plugin.name))

    def initialize(self, name: str) -> None:
        """Initialize a registered plugin."""
        registered = self._get_registered(name)

        if registered.state is not PluginState.REGISTERED:
            raise InvalidPluginStateError(
                f"Plugin cannot be initialized from state: {registered.state.name}"
            )

        registered.plugin.initialize(self._services)
        registered.state = PluginState.INITIALIZED
        self._event_bus.publish(PluginInitialized(plugin_name=name))

    def start(self, name: str) -> None:
        """Start an initialized plugin."""
        registered = self._get_registered(name)

        if registered.state is not PluginState.INITIALIZED:
            raise InvalidPluginStateError(
                f"Plugin cannot be started from state: {registered.state.name}"
            )

        registered.plugin.start()
        registered.state = PluginState.RUNNING
        self._event_bus.publish(PluginStarted(plugin_name=name))

    def stop(self, name: str) -> None:
        """Stop a running plugin."""
        registered = self._get_registered(name)

        if registered.state is not PluginState.RUNNING:
            raise InvalidPluginStateError(
                f"Plugin cannot be stopped from state: {registered.state.name}"
            )

        registered.plugin.stop()
        registered.state = PluginState.STOPPED
        self._event_bus.publish(PluginStopped(plugin_name=name))

    def unload(self, name: str) -> None:
        """Unload and unregister a plugin."""
        registered = self._get_registered(name)

        if registered.state is PluginState.RUNNING:
            raise InvalidPluginStateError("Running plugin cannot be unloaded")

        registered.plugin.unload()
        del self._plugins[name]
        self._event_bus.publish(PluginUnloaded(plugin_name=name))

    def get(self, name: str) -> Plugin:
        """Return a registered plugin."""
        return self._get_registered(name).plugin

    def state(self, name: str) -> PluginState:
        """Return the current state of a registered plugin."""
        return self._get_registered(name).state

    def plugins(self) -> list[Plugin]:
        """Return registered plugins."""
        return [registered.plugin for registered in self._plugins.values()]

    def _get_registered(self, name: str) -> RegisteredPlugin:
        """Return a registered plugin entry."""
        if name not in self._plugins:
            raise PluginNotRegisteredError(f"Plugin not registered: {name}")

        return self._plugins[name]
