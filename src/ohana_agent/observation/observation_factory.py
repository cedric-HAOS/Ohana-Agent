from ohana_agent.observation.observation import Observation
from ohana_agent.observation.observation_status import ObservationStatus


class ObservationFactory:
    """Factory used to create standard observations."""

    def create(
        self,
        *,
        node: str,
        service: str,
        capability: str,
        status: ObservationStatus,
        success: bool,
        message: str,
        source: str,
        latency_ms: float | None = None,
        metadata: dict | None = None,
    ) -> Observation:
        return Observation(
            node=node,
            service=service,
            capability=capability,
            status=status,
            success=success,
            message=message,
            source=source,
            latency_ms=latency_ms,
            metadata=metadata or {},
        )
