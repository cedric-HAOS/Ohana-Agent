from dataclasses import dataclass, field

import pytest

from observer import Observation, ObservationPublished, ObservationStatus
from observer.plugin_observation_dispatcher import (
    PluginObservationDispatcher,
)
from plugin.plugin_command import PluginCommand


@dataclass
class FakePluginObservationExecutor:
    """Record structured commands received by the dispatcher."""

    commands: list[PluginCommand] = field(default_factory=list)

    def execute_command(
        self,
        command: PluginCommand,
    ) -> ObservationPublished:
        self.commands.append(command)

        observation = Observation(
            node="INFRA-01",
            service=command.target_name,
            capability=command.source,
            status=ObservationStatus.HEALTHY,
            success=True,
            message="Executed.",
            source=command.source,
        )

        return ObservationPublished(observation=observation)


def test_dispatcher_dispatches_plugin_command() -> None:
    executor = FakePluginObservationExecutor()
    dispatcher = PluginObservationDispatcher(executor=executor)

    event = dispatcher.execute(
        "dns.resolve",
        {
            "hostname": "example.com",
        },
    )

    assert len(executor.commands) == 1

    command = executor.commands[0]

    assert command.plugin_name == "dns"
    assert command.operation == "resolve"
    assert command.target_name == "dns"
    assert command.arguments == {
        "hostname": "example.com",
    }
    assert command.source == "dns.resolve"

    assert event.observation.service == "dns"
    assert event.observation.capability == "dns.resolve"


def test_dispatcher_accepts_none_arguments() -> None:
    executor = FakePluginObservationExecutor()
    dispatcher = PluginObservationDispatcher(executor=executor)

    dispatcher.execute("dns.resolve")

    assert executor.commands[0].arguments == {}


@pytest.mark.parametrize(
    "command",
    [
        "",
        "   ",
        "dns",
        ".resolve",
        "dns.",
    ],
)
def test_dispatcher_rejects_invalid_plugin_command(
    command: str,
) -> None:
    dispatcher = PluginObservationDispatcher(
        executor=FakePluginObservationExecutor(),
    )

    with pytest.raises(ValueError):
        dispatcher.execute(command)


def test_dispatcher_uses_service_id_as_observation_target() -> None:
    command = PluginObservationDispatcher.parse(
        "dns.resolve",
        arguments={
            "hostname": "example.com",
            "server": "192.168.1.12",
            "service_id": "dns-secondary",
        },
    )

    assert command.target_name == "dns-secondary"
    assert command.arguments["service_id"] == "dns-secondary"


def test_dispatcher_uses_device_id_as_presence_target() -> None:
    command = PluginObservationDispatcher.parse(
        "network.reachable",
        arguments={
            "address": "192.168.1.10",
            "device_id": "infra-01",
        },
    )

    assert command.target_name == "infra-01"
    assert command.arguments["device_id"] == "infra-01"
