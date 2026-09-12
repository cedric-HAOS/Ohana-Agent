from pathlib import Path

from ohana_agent.plugins.runtime.plugin_descriptor import PluginDescriptor


class LocalDirectoryProvider:
    """Discovers plugins from a local directory."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def discover(self) -> tuple[PluginDescriptor, ...]:
        """Discover plugins from subdirectories containing plugin.py."""
        if not self._root.exists():
            return ()

        if not self._root.is_dir():
            return ()

        descriptors: list[PluginDescriptor] = []

        for path in sorted(self._root.iterdir()):
            if not path.is_dir():
                continue

            plugin_file = path / "plugin.py"

            if not plugin_file.is_file():
                continue

            descriptors.append(
                PluginDescriptor(
                    name=path.name,
                    path=path,
                )
            )

        return tuple(descriptors)
