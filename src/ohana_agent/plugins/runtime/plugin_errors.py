class PluginError(Exception):
    """Base exception for plugin-related errors."""


class PluginAlreadyLoadedError(PluginError):
    """Raised when a plugin is already loaded."""


class PluginNotFoundError(PluginError):
    """Raised when a plugin cannot be found."""


class PluginLoadError(PluginError):
    """Raised when a plugin cannot be loaded."""
