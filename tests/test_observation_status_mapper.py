from ohana_agent.observation import ObservationStatus, ObservationStatusMapper


def test_mapper_returns_unknown_when_success_is_none() -> None:
    mapper = ObservationStatusMapper()

    assert mapper.from_success(None) == ObservationStatus.UNKNOWN


def test_mapper_returns_healthy_when_success_is_true() -> None:
    mapper = ObservationStatusMapper()

    assert mapper.from_success(True) == ObservationStatus.HEALTHY


def test_mapper_returns_unhealthy_when_success_is_false() -> None:
    mapper = ObservationStatusMapper()

    assert mapper.from_success(False) == ObservationStatus.UNHEALTHY
