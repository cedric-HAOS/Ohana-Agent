from dataclasses import dataclass


@dataclass(frozen=True)
class PluginRegistered:
    """Event emitted when a plugin is registered."""

    plugin_name: str


@dataclass(frozen=True)
class PluginUnregistered:
    """Event emitted when a plugin is unregistered."""

    plugin_name: str


@dataclass(frozen=True)
class PluginLoadFailed:
    """Event emitted when a plugin fails to load."""

    plugin_name: str
    reason: str
