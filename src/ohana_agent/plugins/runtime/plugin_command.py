"""Plugin command model."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PluginCommand:
    """Describe an operation to execute through a plugin."""

    plugin_name: str
    operation: str
    target_name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plugin_name.strip():
            raise ValueError("plugin_name must not be empty.")

        if not self.operation.strip():
            raise ValueError("operation must not be empty.")

        if not self.target_name.strip():
            raise ValueError("target_name must not be empty.")

    @property
    def source(self) -> str:
        """Return the canonical command source."""
        return f"{self.plugin_name}.{self.operation}"
