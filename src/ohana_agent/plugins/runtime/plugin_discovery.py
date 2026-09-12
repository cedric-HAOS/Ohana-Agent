from ohana_agent.plugins.runtime.discovery.discovery_provider import DiscoveryProvider
from ohana_agent.plugins.runtime.plugin_descriptor import PluginDescriptor


class PluginDiscovery:
    """Discovers plugins using discovery providers."""

    def __init__(
        self,
        providers: tuple[DiscoveryProvider, ...] = (),
    ) -> None:
        self._providers = list(providers)

    @property
    def providers(self) -> tuple[DiscoveryProvider, ...]:
        return tuple(self._providers)

    def add_provider(
        self,
        provider: DiscoveryProvider,
    ) -> None:
        self._providers.append(provider)

    def discover(self) -> tuple[PluginDescriptor, ...]:
        descriptors: list[PluginDescriptor] = []

        for provider in self._providers:
            descriptors.extend(provider.discover())

        return tuple(descriptors)
