import pytest

from ohana_agent.observation import ObserverResult
from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_errors import (
    PluginAlreadyLoadedError,
    PluginNotFoundError,
)
from ohana_agent.plugins.runtime.plugin_manifest import PluginManifest
from ohana_agent.plugins.runtime.plugin_registry import PluginRegistry


class FakePlugin(Plugin):
    def __init__(self, name: str = "fake") -> None:
        self._manifest = PluginManifest(
            name=name,
            version="1.0.0",
            author="Ohana",
            description="Fake plugin",
        )
        self.registered_context = None

    def execute(self, **kwargs: object) -> ObserverResult:
        """Execute the fake plugin."""
        return ObserverResult(
            success=True,
            latency=0.0,
            check="test",
        )

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    def register(self, context: object) -> None:
        self.registered_context = context


def test_plugin_registry_is_empty_by_default() -> None:
    registry = PluginRegistry()

    assert registry.count == 0
    assert registry.plugins == ()


def test_plugin_registry_adds_plugin() -> None:
    registry = PluginRegistry()
    plugin = FakePlugin("dns")

    registry.add(plugin)

    assert registry.count == 1
    assert registry.get("dns") is plugin


def test_plugin_registry_refuses_duplicate_plugin() -> None:
    registry = PluginRegistry()

    registry.add(FakePlugin("dns"))

    with pytest.raises(PluginAlreadyLoadedError):
        registry.add(FakePlugin("dns"))


def test_plugin_registry_get_unknown_plugin_raises() -> None:
    registry = PluginRegistry()

    with pytest.raises(PluginNotFoundError):
        registry.get("unknown")


def test_plugin_registry_has_plugin() -> None:
    registry = PluginRegistry()

    registry.add(FakePlugin("dns"))

    assert registry.has("dns") is True


def test_plugin_registry_does_not_have_unknown_plugin() -> None:
    registry = PluginRegistry()

    assert registry.has("unknown") is False


def test_plugin_registry_removes_plugin() -> None:
    registry = PluginRegistry()

    registry.add(FakePlugin("dns"))
    registry.remove("dns")

    assert registry.count == 0
    assert registry.has("dns") is False


def test_plugin_registry_remove_unknown_plugin_raises() -> None:
    registry = PluginRegistry()

    with pytest.raises(PluginNotFoundError):
        registry.remove("unknown")


def test_plugin_registry_clears_plugins() -> None:
    registry = PluginRegistry()

    registry.add(FakePlugin("dns"))
    registry.add(FakePlugin("mqtt"))

    registry.clear()

    assert registry.count == 0
    assert registry.plugins == ()


def test_plugin_registry_returns_plugins() -> None:
    registry = PluginRegistry()
    dns = FakePlugin("dns")
    mqtt = FakePlugin("mqtt")

    registry.add(dns)
    registry.add(mqtt)

    assert registry.plugins == (dns, mqtt)
