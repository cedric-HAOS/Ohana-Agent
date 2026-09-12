"""Infrastructure endpoint model."""

from dataclasses import dataclass, field
from typing import Any

from ohana_agent.infrastructure.enums import EndpointType


@dataclass(slots=True)
class Endpoint:
    """Represents an access point exposed by an infrastructure node."""

    type: EndpointType
    address: str
    port: int | None = None
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_enabled(self) -> bool:
        """Return whether this endpoint is enabled."""
        return self.enabled
