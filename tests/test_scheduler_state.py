from ohana_agent.scheduler import SchedulerState


def test_scheduler_state_values() -> None:
    assert SchedulerState.STOPPED == "stopped"
    assert SchedulerState.STARTING == "starting"
    assert SchedulerState.RUNNING == "running"
    assert SchedulerState.STOPPING == "stopping"
