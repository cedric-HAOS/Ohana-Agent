from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from observer import Observation, ObservationPublished, ObservationStatus
from observer.plugin_observation_dispatcher import (
    PluginObservationDispatcher,
)
from plugin.plugin_command import PluginCommand
from scheduler import (
    DispatcherTaskExecutor,
    IntervalTrigger,
    Task,
    TaskState,
)


@dataclass
class FakePluginObservationExecutor:
    commands: list[PluginCommand] = field(default_factory=list)

    def execute_command(
        self,
        command: PluginCommand,
    ) -> ObservationPublished:
        self.commands.append(command)

        return ObservationPublished(
            observation=Observation(
                node="INFRA-01",
                service=command.target_name,
                capability=command.source,
                status=ObservationStatus.HEALTHY,
                success=True,
                message="Executed.",
                source=command.source,
            )
        )


class FakeDispatcher:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, object]]] = []

    def execute(
        self,
        command: str,
        arguments: dict[str, object] | None = None,
    ) -> None:
        self.executed.append((command, arguments or {}))


class FailingDispatcher:
    def execute(
        self,
        command: str,
        arguments: dict[str, object] | None = None,
    ) -> None:
        msg = "dispatcher failed"
        raise RuntimeError(msg)


def test_dispatcher_task_executor_executes_task_command() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    dispatcher = FakeDispatcher()
    executor = DispatcherTaskExecutor(dispatcher)

    task = Task(
        command="health.check",
        trigger=IntervalTrigger(timedelta(seconds=30)),
        arguments={"verbose": True},
    )

    result = executor.execute(task, now)

    assert dispatcher.executed == [("health.check", {"verbose": True})]
    assert result.task_id == task.id
    assert result.command == "health.check"
    assert result.success is True
    assert result.error is None
    assert task.state == TaskState.WAITING
    assert task.last_started_at == now
    assert task.last_finished_at == now
    assert task.execution_count == 1


def test_dispatcher_task_executor_dispatches_due_wake_requests() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    dispatcher = FakeDispatcher()
    calls: list[datetime] = []
    executor = DispatcherTaskExecutor(
        dispatcher,
        wake_dispatcher=calls.append,
    )

    task = Task(
        command="jobs.wake.dispatch",
        trigger=IntervalTrigger(timedelta(seconds=30)),
    )

    result = executor.execute(task, now)

    assert result.success is True
    assert calls == [now]
    assert dispatcher.executed == []


def test_dispatcher_task_executor_handles_dispatcher_failure() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    dispatcher = FailingDispatcher()
    executor = DispatcherTaskExecutor(dispatcher)

    task = Task(
        command="health.check",
        trigger=IntervalTrigger(timedelta(seconds=30)),
    )

    result = executor.execute(task, now)

    assert result.task_id == task.id
    assert result.command == "health.check"
    assert result.success is False
    assert result.error == "dispatcher failed"
    assert task.state == TaskState.WAITING
    assert task.last_started_at == now
    assert task.last_failed_at == now
    assert task.last_error == "dispatcher failed"
    assert task.execution_count == 1


def test_dispatcher_task_executor_executes_plugin_observation_command() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    plugin_executor = FakePluginObservationExecutor()
    dispatcher = PluginObservationDispatcher(
        executor=plugin_executor,
    )
    task_executor = DispatcherTaskExecutor(
        dispatcher=dispatcher,
    )

    task = Task(
        command="dns.resolve",
        trigger=IntervalTrigger(timedelta(seconds=30)),
        arguments={
            "hostname": "example.com",
        },
    )

    result = task_executor.execute(task, now)

    assert result.success is True
    assert len(plugin_executor.commands) == 1

    command = plugin_executor.commands[0]

    assert command.plugin_name == "dns"
    assert command.operation == "resolve"
    assert command.target_name == "dns"
    assert command.arguments == {
        "hostname": "example.com",
    }
    assert command.source == "dns.resolve"
    assert task.state is TaskState.WAITING
    assert task.execution_count == 1


def test_dispatcher_task_executor_suspends_once_and_resumes() -> None:
    from types import SimpleNamespace

    from monitoring import MonitoringScheduleRegistry

    class ScheduleDispatcher(FakeDispatcher):
        def __init__(self) -> None:
            super().__init__()
            self.suspended: list[tuple[str, str]] = []

        def publish_suspended(
            self,
            command: str,
            arguments: dict[str, object],
            *,
            reason: str,
            next_activation: datetime | None,
        ) -> None:
            del arguments, next_activation
            self.suspended.append((command, reason))

    registry = MonitoringScheduleRegistry()
    registry.replace_from_infrastructure(
        SimpleNamespace(
            topology=SimpleNamespace(
                devices=[
                    SimpleNamespace(
                        id="sun-01",
                        node="sun-node",
                        metadata={
                            "monitoring_schedule": {
                                "timezone": "Europe/Paris",
                                "periods": [
                                    {
                                        "days": ["thursday"],
                                        "start": "07:00",
                                        "end": "22:00",
                                    }
                                ],
                                "startup_grace_seconds": 0,
                            }
                        },
                    )
                ]
            )
        )
    )
    dispatcher = ScheduleDispatcher()
    executor = DispatcherTaskExecutor(
        dispatcher=dispatcher,
        monitoring_registry=registry,
    )
    task = Task(
        command="network.reachable",
        trigger=IntervalTrigger(timedelta(seconds=30)),
        arguments={"device_id": "sun-01"},
        metadata={"node_id": "sun-node"},
    )

    suspended_at = datetime(2026, 7, 30, 4, 0, tzinfo=UTC)
    active_at = datetime(2026, 7, 30, 6, 0, tzinfo=UTC)

    assert executor.execute(task, suspended_at).success is True
    assert executor.execute(task, suspended_at).success is True
    assert len(dispatcher.suspended) == 1
    assert dispatcher.executed == []

    assert executor.execute(task, active_at).success is True
    assert dispatcher.executed == [("network.reachable", {"device_id": "sun-01"})]
