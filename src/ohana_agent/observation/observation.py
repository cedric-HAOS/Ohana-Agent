from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from ohana_agent.observation.observation_status import ObservationStatus


@dataclass(slots=True, frozen=True)
class Observation:
    """Standard observation produced by Ohana-Agent."""

    node: str

    service: str

    capability: str

    status: ObservationStatus

    success: bool

    message: str

    source: str

    id: UUID = field(default_factory=uuid4)

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    latency_ms: float | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
