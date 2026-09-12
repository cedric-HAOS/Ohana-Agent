"""Observation JSON serializer."""

import json
from typing import Any

from ohana_agent.observation.observation import Observation


class ObservationSerializer:
    """Serializes standard observations."""

    def to_dict(
        self,
        observation: Observation,
    ) -> dict[str, Any]:
        """Convert an observation to a serializable dictionary."""
        return {
            "id": str(observation.id),
            "timestamp": observation.timestamp.isoformat(),
            "source": observation.source,
            "node": observation.node,
            "service": observation.service,
            "capability": observation.capability,
            "status": observation.status.value,
            "success": observation.success,
            "latency_ms": observation.latency_ms,
            "message": observation.message,
            "metadata": observation.metadata.copy(),
        }

    def to_json(
        self,
        observation: Observation,
        *,
        indent: int | None = None,
    ) -> str:
        """Serialize an observation to JSON."""
        return json.dumps(
            self.to_dict(observation),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
        )
