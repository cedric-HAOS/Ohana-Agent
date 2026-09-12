from ohana_agent.observation.observation_status import ObservationStatus


class ObservationStatusMapper:
    """Maps raw check results to standard observation statuses."""

    def from_success(
        self,
        success: bool | None,
    ) -> ObservationStatus:
        """Map a success value to an observation status."""

        if success is None:
            return ObservationStatus.UNKNOWN

        if success:
            return ObservationStatus.HEALTHY

        return ObservationStatus.UNHEALTHY
