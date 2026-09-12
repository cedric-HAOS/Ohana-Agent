from typing import Protocol

from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_descriptor import PluginDescriptor


class PluginFactory(Protocol):
    """Contract for plugin factories."""

    def create(self, descriptor: PluginDescriptor) -> Plugin:
        """Create a plugin from a descriptor."""
