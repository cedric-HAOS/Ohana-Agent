from typing import Protocol

from ohana_agent.plugins.runtime.plugin_descriptor import PluginDescriptor


class DiscoveryProvider(Protocol):
    """Contract for plugin discovery providers."""

    def discover(self) -> tuple[PluginDescriptor, ...]:
        """Discover available plugins."""
