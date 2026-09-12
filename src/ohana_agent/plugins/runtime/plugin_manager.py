from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_context import PluginContext
from ohana_agent.plugins.runtime.plugin_descriptor import PluginDescriptor
from ohana_agent.plugins.runtime.plugin_discovery import PluginDiscovery
from ohana_agent.plugins.runtime.plugin_errors import PluginNotFoundError
from ohana_agent.plugins.runtime.plugin_events import (
    PluginRegistered,
    PluginUnregistered,
)
from ohana_agent.plugins.runtime.plugin_loader import PluginLoader
from ohana_agent.plugins.runtime.plugin_registry import PluginRegistry
from ohana_agent.plugins.runtime.plugin_runtime import PluginRuntime
from ohana_agent.plugins.runtime.plugin_state import PluginState


class PluginManager:
    """Orchestrates plugin discovery, loading and registration."""

    def __init__(
        self,
        *,
        context: PluginContext,
        discovery: PluginDiscovery | None = None,
        loader: PluginLoader | None = None,
        registry: PluginRegistry | None = None,
        runtime: PluginRuntime | None = None,
    ) -> None:
        self._context = context
        self._discovery = discovery or PluginDiscovery()
        self._loader = loader or PluginLoader()
        self._registry = registry or PluginRegistry()
        self._runtime = runtime or PluginRuntime()

    @property
    def discovery(self) -> PluginDiscovery:
        """Return the discovery service."""
        return self._discovery

    @property
    def loader(self) -> PluginLoader:
        """Return the loader."""
        return self._loader

    @property
    def registry(self) -> PluginRegistry:
        """Return the registry."""
        return self._registry

    @property
    def runtime(self) -> PluginRuntime:
        """Return the runtime."""
        return self._runtime

    @property
    def plugins(self) -> tuple[Plugin, ...]:
        """Return all registered plugins."""
        return self._registry.plugins

    @property
    def count(self) -> int:
        """Return the number of registered plugins."""
        return self._registry.count

    def discover(self) -> tuple[PluginDescriptor, ...]:
        """Discover available plugins."""
        descriptors = self._discovery.discover()

        for descriptor in descriptors:
            self._runtime.set_state(
                descriptor.name,
                PluginState.DISCOVERED,
            )

        return descriptors

    def load(
        self,
        descriptors: tuple[PluginDescriptor, ...],
    ) -> tuple[Plugin, ...]:
        """Load plugins from descriptors."""
        plugins = self._loader.load_all(descriptors)

        for plugin in plugins:
            self._runtime.set_state(
                plugin.manifest.name,
                PluginState.LOADED,
            )

        return plugins

    def register(self, plugin: Plugin) -> None:
        """Register a plugin."""
        plugin.register(self._context)
        self._registry.add(plugin)

        name = plugin.manifest.name

        self._runtime.set_state(
            name,
            PluginState.REGISTERED,
        )

        self._publish(
            PluginRegistered(plugin_name=name),
        )

    def register_all(
        self,
        plugins: tuple[Plugin, ...],
    ) -> None:
        """Register multiple plugins."""
        for plugin in plugins:
            self.register(plugin)

    def unregister(self, name: str) -> None:
        """Unregister a plugin."""
        if not self._registry.has(name):
            raise PluginNotFoundError(f"Plugin not found: {name}")

        self._registry.remove(name)

        self._runtime.set_state(
            name,
            PluginState.UNLOADED,
        )

        self._publish(
            PluginUnregistered(plugin_name=name),
        )

    def get(self, name: str) -> Plugin:
        """Return a plugin by name."""
        return self._registry.get(name)

    def has(self, name: str) -> bool:
        """Return whether a plugin is registered."""
        return self._registry.has(name)

    def start(self) -> tuple[Plugin, ...]:
        """Discover, load and register all plugins."""
        descriptors = self.discover()
        plugins = self.load(descriptors)
        self.register_all(plugins)

        return plugins

    def _publish(self, event: object) -> None:
        self._context.event_bus.publish(event)
