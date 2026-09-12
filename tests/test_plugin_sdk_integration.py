from ohana_agent.plugins.runtime.discovery.local_directory_provider import (
    LocalDirectoryProvider,
)
from ohana_agent.plugins.runtime.plugin_context import PluginContext
from ohana_agent.plugins.runtime.plugin_discovery import PluginDiscovery
from ohana_agent.plugins.runtime.plugin_manager import PluginManager
from ohana_agent.plugins.runtime.plugin_state import PluginState


class FakeEventBus:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def test_plugin_sdk_end_to_end(tmp_path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()

    echo_dir = plugins_dir / "echo"
    echo_dir.mkdir()

    (echo_dir / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (echo_dir / "plugin.py").write_text(
        """
from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_manifest import PluginManifest
from ohana_agent.observation.observer_result import ObserverResult


class EchoPlugin(Plugin):

    @property
    def manifest(self):
        return PluginManifest(
            name="echo",
            version="1.0.0",
            author="Ohana",
            description="Echo plugin",
        )

    def register(self, context):
        self.context = context

    def execute(self, **kwargs):
        return ObserverResult(
            success=True,
            latency=0.0,
            check="echo",
        )


def create_plugin():
    return EchoPlugin()
""",
        encoding="utf-8",
    )

    event_bus = FakeEventBus()

    context = PluginContext(
        event_bus=event_bus,
        scheduler=object(),
        dispatcher=object(),
        memory=object(),
        capability_manager=object(),
        configuration=object(),
        runtime=object(),
    )

    discovery = PluginDiscovery((LocalDirectoryProvider(plugins_dir),))

    manager = PluginManager(
        context=context,
        discovery=discovery,
    )

    plugins = manager.start()

    assert len(plugins) == 1

    plugin = manager.get("echo")

    assert plugin.manifest.name == "echo"

    assert manager.count == 1

    assert manager.runtime.get_state("echo") == PluginState.REGISTERED

    assert manager.has("echo")

    assert len(event_bus.events) == 1
