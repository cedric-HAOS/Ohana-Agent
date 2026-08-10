"""Mapping of Ohana-Agent observations to Ohana-Vision payloads."""

from typing import Any

from observer.observation import Observation
from observer.observation_status import ObservationStatus


class VisionObservationMapper:
    """Convert Agent observations to the Ohana-Vision REST contract."""

    _STATUS_MAPPING = {
        ObservationStatus.HEALTHY: "healthy",
        # Vision has no dedicated suspended state. A scheduled suspension is
        # not a failure, so expose it as unknown and preserve the suspension
        # details in observation metadata.
        ObservationStatus.SUSPENDED: "unknown",
        ObservationStatus.DEGRADED: "degraded",
        ObservationStatus.UNHEALTHY: "unavailable",
        ObservationStatus.UNKNOWN: "unknown",
    }

    def to_payload(
        self,
        observation: Observation,
    ) -> dict[str, Any]:
        """Build the payload expected by Ohana-Vision."""
        metadata = observation.metadata.copy()

        metadata["agent_observation"] = {
            "id": str(observation.id),
            "source": observation.source,
            "success": observation.success,
            "message": observation.message,
        }

        return {
            "observation_id": str(observation.id),
            "capability_id": observation.capability,
            "service_id": observation.service,
            "node_id": observation.node,
            "status": self._STATUS_MAPPING[observation.status],
            "observed_at": observation.timestamp.isoformat(),
            "message": observation.message,
            "latency_ms": observation.latency_ms,
            "metadata": metadata,
        }
