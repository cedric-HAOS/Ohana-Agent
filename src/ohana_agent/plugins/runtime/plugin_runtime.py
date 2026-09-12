from collections.abc import Iterator

from ohana_agent.plugins.runtime.plugin_state import PluginState


class PluginRuntime:
    """Stores runtime states for plugins."""

    def __init__(self) -> None:
        self._states: dict[str, PluginState] = {}

    @property
    def plugins(self) -> tuple[str, ...]:
        return tuple(self._states)

    @property
    def count(self) -> int:
        return len(self)

    def __len__(self) -> int:
        return len(self._states)

    def __contains__(self, plugin_name: str) -> bool:
        return plugin_name in self._states

    def __iter__(self) -> Iterator[tuple[str, PluginState]]:
        return iter(self._states.items())

    def set_state(self, plugin_name: str, state: PluginState) -> None:
        self._states[plugin_name] = state

    def get_state(self, plugin_name: str) -> PluginState | None:
        return self._states.get(plugin_name)

    def state(self, plugin_name: str) -> PluginState | None:
        """Return the runtime state of a plugin.

        Deprecated alias for get_state().
        """
        return self.get_state(plugin_name)

    def has(self, plugin_name: str) -> bool:
        return plugin_name in self

    def remove(self, plugin_name: str) -> None:
        self._states.pop(plugin_name, None)

    def clear(self) -> None:
        self._states.clear()
