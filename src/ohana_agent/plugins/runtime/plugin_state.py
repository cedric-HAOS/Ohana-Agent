from enum import StrEnum


class PluginState(StrEnum):
    """Lifecycle states of a plugin."""

    DISCOVERED = "discovered"
    LOADED = "loaded"
    REGISTERED = "registered"
    FAILED = "failed"
    UNLOADED = "unloaded"
