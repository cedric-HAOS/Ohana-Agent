from ohana_agent.observation import ObservationStatus


def test_observation_status_values() -> None:
    assert ObservationStatus.UNKNOWN == "unknown"
    assert ObservationStatus.HEALTHY == "healthy"
    assert ObservationStatus.DEGRADED == "degraded"
    assert ObservationStatus.UNHEALTHY == "unhealthy"
