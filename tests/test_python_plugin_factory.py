import pytest

from ohana_agent.plugins.runtime.factory.python_plugin_factory import (
    PythonPluginFactory,
)
from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_descriptor import PluginDescriptor
from ohana_agent.plugins.runtime.plugin_errors import PluginLoadError


def test_python_plugin_factory_creates_plugin(tmp_path) -> None:
    plugin_dir = tmp_path / "echo"
    plugin_dir.mkdir()

    (plugin_dir / "plugin.py").write_text(
        """
from ohana_agent.observation.observer_result import ObserverResult
from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_manifest import PluginManifest


class EchoPlugin(Plugin):
    @property
    def manifest(self):
        return PluginManifest(name="echo", version="1.0.0")

    def register(self, context):
        pass

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

    factory = PythonPluginFactory()
    descriptor = PluginDescriptor(name="echo", path=plugin_dir)

    plugin = factory.create(descriptor)

    assert isinstance(plugin, Plugin)
    assert plugin.manifest.name == "echo"


def test_python_plugin_factory_raises_when_plugin_file_is_missing(tmp_path) -> None:
    descriptor = PluginDescriptor(name="missing", path=tmp_path / "missing")

    factory = PythonPluginFactory()

    with pytest.raises(PluginLoadError):
        factory.create(descriptor)


def test_python_plugin_factory_raises_when_create_plugin_is_missing(
    tmp_path,
) -> None:
    plugin_dir = tmp_path / "broken"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text("", encoding="utf-8")

    descriptor = PluginDescriptor(name="broken", path=plugin_dir)

    factory = PythonPluginFactory()

    with pytest.raises(PluginLoadError):
        factory.create(descriptor)


def test_python_plugin_factory_raises_when_factory_returns_invalid_object(
    tmp_path,
) -> None:
    plugin_dir = tmp_path / "invalid"
    plugin_dir.mkdir()

    (plugin_dir / "plugin.py").write_text(
        """
def create_plugin():
    return object()
""",
        encoding="utf-8",
    )

    descriptor = PluginDescriptor(name="invalid", path=plugin_dir)

    factory = PythonPluginFactory()

    with pytest.raises(PluginLoadError):
        factory.create(descriptor)
