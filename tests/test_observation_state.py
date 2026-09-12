from ohana_agent.observation import ObservationState


def test_observation_state_idle() -> None:
    assert ObservationState.IDLE.value == "idle"


def test_observation_state_running() -> None:
    assert ObservationState.RUNNING.value == "running"


def test_observation_state_disabled() -> None:
    assert ObservationState.DISABLED.value == "disabled"
