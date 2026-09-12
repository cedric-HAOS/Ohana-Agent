import importlib.util
from pathlib import Path
from types import ModuleType

from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_descriptor import PluginDescriptor
from ohana_agent.plugins.runtime.plugin_errors import PluginLoadError


class PythonPluginFactory:
    """Creates plugins from Python plugin.py files."""

    def create(self, descriptor: PluginDescriptor) -> Plugin:
        """Create a plugin instance from a descriptor."""
        plugin_file = descriptor.path / "plugin.py"

        if not plugin_file.is_file():
            raise PluginLoadError(f"Plugin file not found: {plugin_file}")

        module = self._load_module(descriptor.name, plugin_file)

        create_plugin = getattr(module, "create_plugin", None)

        if create_plugin is None:
            raise PluginLoadError(
                f"Plugin factory function not found: {descriptor.name}"
            )

        plugin = create_plugin()

        if not isinstance(plugin, Plugin):
            raise PluginLoadError(f"Factory did not return a Plugin: {descriptor.name}")

        return plugin

    def _load_module(self, name: str, path: Path) -> ModuleType:
        module_name = f"ohana_plugin_{name}"

        spec = importlib.util.spec_from_file_location(module_name, path)

        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Unable to load plugin module: {path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return module
