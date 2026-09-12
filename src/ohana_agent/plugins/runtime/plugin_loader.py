from ohana_agent.plugins.runtime.factory.plugin_factory import PluginFactory
from ohana_agent.plugins.runtime.factory.python_plugin_factory import (
    PythonPluginFactory,
)
from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_descriptor import PluginDescriptor


class PluginLoader:
    """Loads plugins using a plugin factory."""

    def __init__(self, factory: PluginFactory | None = None) -> None:
        self._factory = factory or PythonPluginFactory()

    @property
    def factory(self) -> PluginFactory:
        """Return the configured plugin factory."""
        return self._factory

    def load(self, descriptor: PluginDescriptor) -> Plugin:
        """Load a plugin from a descriptor."""
        return self._factory.create(descriptor)

    def load_all(self, descriptors: tuple[PluginDescriptor, ...]) -> tuple[Plugin, ...]:
        """Load all plugins from descriptors."""
        return tuple(self.load(descriptor) for descriptor in descriptors)
