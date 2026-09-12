from ohana_agent.observation import ObservationRuntime, ObservationState


def test_observation_runtime_defaults() -> None:
    runtime = ObservationRuntime()

    assert runtime.state == ObservationState.IDLE
    assert runtime.last_result is None
    assert runtime.last_execution is None
    assert runtime.next_execution is None


def test_observation_runtime_state_can_be_changed() -> None:
    runtime = ObservationRuntime()

    runtime.state = ObservationState.RUNNING

    assert runtime.state == ObservationState.RUNNING
