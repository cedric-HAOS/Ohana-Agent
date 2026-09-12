from pathlib import Path

from ohana_agent.plugins.runtime.plugin_descriptor import PluginDescriptor
from ohana_agent.plugins.runtime.plugin_discovery import PluginDiscovery


class FakeDiscoveryProvider:
    def __init__(self, descriptors: tuple[PluginDescriptor, ...]) -> None:
        self._descriptors = descriptors

    def discover(self) -> tuple[PluginDescriptor, ...]:
        return self._descriptors


def test_plugin_discovery_has_no_provider_by_default() -> None:
    discovery = PluginDiscovery()

    assert discovery.providers == ()


def test_plugin_discovery_returns_empty_tuple_without_provider() -> None:
    discovery = PluginDiscovery()

    assert discovery.discover() == ()


def test_plugin_discovery_returns_provider_descriptors() -> None:
    descriptor = PluginDescriptor(
        name="dns",
        path=Path("plugins/dns"),
    )

    provider = FakeDiscoveryProvider((descriptor,))
    discovery = PluginDiscovery((provider,))

    assert discovery.discover() == (descriptor,)


def test_plugin_discovery_aggregates_multiple_providers() -> None:
    dns = PluginDescriptor(
        name="dns",
        path=Path("plugins/dns"),
    )
    mqtt = PluginDescriptor(
        name="mqtt",
        path=Path("plugins/mqtt"),
    )

    discovery = PluginDiscovery(
        (
            FakeDiscoveryProvider((dns,)),
            FakeDiscoveryProvider((mqtt,)),
        )
    )

    assert discovery.discover() == (dns, mqtt)
