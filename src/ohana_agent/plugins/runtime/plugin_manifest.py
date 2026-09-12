from dataclasses import dataclass


@dataclass(frozen=True)
class PluginManifest:
    """Immutable metadata describing a plugin."""

    name: str
    version: str
    author: str = "Ohana"
    description: str = ""
