"""Tests for the network equipment presence plugin."""

import pytest

from infrastructure import HealthStatus
from plugin.plugin_context import PluginContext
from plugin.plugin_runtime import PluginState
from plugins.network.network_config import NetworkConfig
from plugins.network.network_plugin import NetworkPlugin
from plugins.network.network_probe_result import NetworkProbeResult


class FakeNetworkCheck:
    def __init__(self, results: list[NetworkProbeResult]) -> None:
        self.results = iter(results)
        self.calls: list[tuple[str, float, int]] = []

    def check(
        self,
        address: str,
        *,
        timeout: float,
        retries: int,
    ) -> NetworkProbeResult:
        self.calls.append((address, timeout, retries))
        return next(self.results)


def make_context() -> PluginContext:
    return PluginContext(
        event_bus=object(),
        scheduler=None,
        dispatcher=None,
        memory=None,
        capability_manager=None,
        configuration=None,
        runtime=None,
    )


def test_network_plugin_applies_consecutive_failure_threshold() -> None:
    address = "192.168.1.10"
    plugin = NetworkPlugin(
        check=FakeNetworkCheck(
            [
                NetworkProbeResult(address=address, reachable=False),
                NetworkProbeResult(address=address, reachable=False),
                NetworkProbeResult(address=address, reachable=False),
                NetworkProbeResult(
                    address=address,
                    reachable=True,
                    method="icmp",
                    latency_ms=2.5,
                ),
            ]
        ),
        config=NetworkConfig(failure_threshold=3),
    )

    first = plugin.execute(address=address, device_id="infra-01")
    second = plugin.execute(address=address, device_id="infra-01")
    third = plugin.execute(address=address, device_id="infra-01")
    recovered = plugin.execute(address=address, device_id="infra-01")

    assert first.health is HealthStatus.UNKNOWN
    assert second.health is HealthStatus.UNKNOWN
    assert third.health is HealthStatus.UNHEALTHY
    assert third.metadata["consecutive_failures"] == 3
    assert recovered.health is HealthStatus.HEALTHY
    assert recovered.success is True
    assert recovered.metadata["consecutive_failures"] == 0
    assert recovered.check == "network.reachable"


def test_network_plugin_marks_probe_errors_unknown() -> None:
    plugin = NetworkPlugin(
        check=FakeNetworkCheck(
            [
                NetworkProbeResult(
                    address="192.168.1.10",
                    reachable=None,
                    error="ping unavailable",
                )
            ]
        )
    )

    result = plugin.execute(
        address="192.168.1.10",
        device_id="infra-01",
        node_id="infra-01",
    )

    assert result.health is HealthStatus.UNKNOWN
    assert result.metadata["target_type"] == "device"
    assert result.metadata["device_id"] == "infra-01"
    assert result.metadata["node_id"] == "infra-01"


def test_network_plugin_registers_and_validates_arguments() -> None:
    plugin = NetworkPlugin()

    assert plugin.state is PluginState.LOADED

    plugin.register(make_context())

    assert plugin.state is PluginState.REGISTERED

    with pytest.raises(ValueError, match="address"):
        plugin.execute(address="", device_id="infra-01")

    with pytest.raises(ValueError, match="device_id"):
        plugin.execute(address="192.168.1.10", device_id="")


def test_network_plugin_immediate_test_preserves_failure_history() -> None:
    address = "192.168.1.10"
    plugin = NetworkPlugin(
        check=FakeNetworkCheck(
            [
                NetworkProbeResult(address=address, reachable=False),
                NetworkProbeResult(address=address, reachable=False),
                NetworkProbeResult(address=address, reachable=False),
            ]
        ),
        config=NetworkConfig(failure_threshold=2),
    )

    first = plugin.execute(address=address, device_id="infra-01")
    immediate = plugin.test(address=address, device_id="infra-01")
    second = plugin.execute(address=address, device_id="infra-01")

    assert first.metadata["consecutive_failures"] == 1
    assert immediate.metadata["consecutive_failures"] == 2
    assert second.metadata["consecutive_failures"] == 2
