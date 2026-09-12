from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PluginContext:
    """Immutable context exposed to plugins.

    This object provides access to the public services of the
    Ohana-Agent core without exposing the Application itself.
    """

    event_bus: Any
    scheduler: Any
    dispatcher: Any
    memory: Any
    capability_manager: Any
    configuration: Any
    runtime: Any
