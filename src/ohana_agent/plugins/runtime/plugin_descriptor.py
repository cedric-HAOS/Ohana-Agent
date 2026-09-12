from dataclasses import dataclass
from pathlib import Path

from ohana_agent.plugins.runtime.plugin_manifest import PluginManifest


@dataclass(frozen=True, slots=True)
class PluginDescriptor:
    """Describes a discovered plugin."""

    name: str
    path: Path
    manifest: PluginManifest | None = None
