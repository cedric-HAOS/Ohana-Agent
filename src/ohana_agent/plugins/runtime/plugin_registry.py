from collections.abc import Iterator

from ohana_agent.plugins.runtime.plugin import Plugin
from ohana_agent.plugins.runtime.plugin_errors import (
    PluginAlreadyLoadedError,
    PluginNotFoundError,
)


class PluginRegistry:
    """Stores loaded plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    @property
    def plugins(self) -> tuple[Plugin, ...]:
        return tuple(self._plugins.values())

    @property
    def count(self) -> int:
        return len(self)

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: str) -> bool:
        return name in self._plugins

    def __iter__(self) -> Iterator[Plugin]:
        return iter(self._plugins.values())

    def add(self, plugin: Plugin) -> None:
        name = plugin.manifest.name

        if name in self:
            raise PluginAlreadyLoadedError(f"Plugin already loaded: {name}")

        self._plugins[name] = plugin

    def remove(self, name: str) -> None:
        if name not in self:
            raise PluginNotFoundError(f"Plugin not found: {name}")

        del self._plugins[name]

    def get(self, name: str) -> Plugin:
        if name not in self:
            raise PluginNotFoundError(f"Plugin not found: {name}")

        return self._plugins[name]

    def has(self, name: str) -> bool:
        return name in self

    def clear(self) -> None:
        self._plugins.clear()
