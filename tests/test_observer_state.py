from ohana_agent.observation import ObserverState


def test_observer_state_idle_value() -> None:
    assert ObserverState.IDLE.value == "idle"


def test_observer_state_running_value() -> None:
    assert ObserverState.RUNNING.value == "running"


def test_observer_state_stopped_value() -> None:
    assert ObserverState.STOPPED.value == "stopped"
