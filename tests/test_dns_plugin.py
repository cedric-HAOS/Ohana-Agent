import pytest

from plugins.dns.dns_capability_runtime import DNSCapabilityRuntime
from plugins.dns.dns_check_result import DNSCheckResult
from plugins.dns.dns_config import DNSConfig, DNSPolicyConfig, DNSServerConfig
from plugins.dns.dns_events import DNSCheckFailed, DNSCheckStarted, DNSCheckSucceeded
from plugins.dns.dns_plugin import DNSPlugin
from plugins.dns.dns_runtime import DNSRuntime


class FakeDNSCheck:
    def __init__(self, result: DNSCheckResult) -> None:
        self.result = result
        self.hostname: str | None = None
        self.server: str | None = None

    def check(
        self,
        hostname: str,
        server: str | None = None,
    ) -> DNSCheckResult:
        self.hostname = hostname
        self.server = server
        return self.result


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def test_dns_plugin_runs_dns_check() -> None:
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="example.com",
            healthy=True,
            address="93.184.216.34",
        )
    )

    plugin = DNSPlugin(check=dns_check)

    result = plugin.check("example.com")

    assert dns_check.hostname == "example.com"
    assert result.hostname == "example.com"
    assert result.healthy is True
    assert result.address == "93.184.216.34"
    assert result.error is None


def test_dns_plugin_returns_failed_dns_check() -> None:
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="missing.local",
            healthy=False,
            error="host not found",
        )
    )

    plugin = DNSPlugin(check=dns_check)

    result = plugin.check("missing.local")

    assert dns_check.hostname == "missing.local"
    assert result.hostname == "missing.local"
    assert result.healthy is False
    assert result.address is None
    assert result.error == "host not found"


def test_dns_plugin_publishes_started_and_succeeded_events() -> None:
    event_bus = FakeEventBus()
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="example.com",
            healthy=True,
            address="93.184.216.34",
        )
    )

    plugin = DNSPlugin(check=dns_check, event_bus=event_bus)

    plugin.check("example.com")

    assert event_bus.events == [
        DNSCheckStarted(hostname="example.com"),
        DNSCheckSucceeded(
            hostname="example.com",
            address="93.184.216.34",
        ),
    ]


def test_dns_plugin_publishes_started_and_failed_events() -> None:
    event_bus = FakeEventBus()
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="missing.local",
            healthy=False,
            error="host not found",
        )
    )

    plugin = DNSPlugin(check=dns_check, event_bus=event_bus)

    plugin.check("missing.local")

    assert event_bus.events == [
        DNSCheckStarted(hostname="missing.local"),
        DNSCheckFailed(
            hostname="missing.local",
            error="host not found",
        ),
    ]


def test_dns_plugin_updates_runtime_on_success() -> None:
    runtime = DNSRuntime()
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="example.com",
            healthy=True,
            address="93.184.216.34",
        )
    )

    plugin = DNSPlugin(
        check=dns_check,
        runtime=runtime,
    )

    plugin.check("example.com")

    assert runtime.total_checks == 1
    assert runtime.successful_checks == 1
    assert runtime.failed_checks == 0
    assert runtime.last_hostname == "example.com"
    assert runtime.last_address == "93.184.216.34"
    assert runtime.last_error is None
    assert runtime.healthy is True


def test_dns_plugin_updates_runtime_on_failure() -> None:
    runtime = DNSRuntime()
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="missing.local",
            healthy=False,
            error="host not found",
        )
    )

    plugin = DNSPlugin(
        check=dns_check,
        runtime=runtime,
    )

    plugin.check("missing.local")

    assert runtime.total_checks == 1
    assert runtime.successful_checks == 0
    assert runtime.failed_checks == 1
    assert runtime.last_hostname == "missing.local"
    assert runtime.last_address is None
    assert runtime.last_error == "host not found"
    assert runtime.healthy is False


def test_dns_plugin_returns_empty_statistics() -> None:
    plugin = DNSPlugin()

    statistics = plugin.statistics()

    assert statistics.total_checks == 0
    assert statistics.successful_checks == 0
    assert statistics.failed_checks == 0
    assert statistics.success_rate == 0.0
    assert statistics.healthy is None


def test_dns_plugin_returns_statistics_after_success() -> None:
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="example.com",
            healthy=True,
            address="93.184.216.34",
        )
    )

    plugin = DNSPlugin(check=dns_check)

    plugin.check("example.com")

    statistics = plugin.statistics()

    assert statistics.total_checks == 1
    assert statistics.successful_checks == 1
    assert statistics.failed_checks == 0
    assert statistics.success_rate == 1.0
    assert statistics.healthy is True


def test_dns_plugin_returns_statistics_after_failure() -> None:
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="missing.local",
            healthy=False,
            error="host not found",
        )
    )

    plugin = DNSPlugin(check=dns_check)

    plugin.check("missing.local")

    statistics = plugin.statistics()

    assert statistics.total_checks == 1
    assert statistics.successful_checks == 0
    assert statistics.failed_checks == 1
    assert statistics.success_rate == 0.0
    assert statistics.healthy is False


def test_dns_plugin_uses_default_dns_config() -> None:
    plugin = DNSPlugin()

    assert plugin.config == DNSConfig()
    assert plugin.servers == []
    assert isinstance(plugin.capability_runtime, DNSCapabilityRuntime)


def test_dns_plugin_builds_servers_from_config() -> None:
    config = DNSConfig(
        servers=[
            DNSServerConfig(
                name="DNS-01",
                address="192.168.1.54",
            ),
            DNSServerConfig(
                name="DNS-02",
                address="192.168.1.55",
            ),
        ]
    )

    plugin = DNSPlugin(config=config)

    assert len(plugin.servers) == 2
    assert plugin.servers[0].name == "DNS-01"
    assert plugin.servers[0].address == "192.168.1.54"
    assert plugin.servers[1].name == "DNS-02"
    assert plugin.servers[1].address == "192.168.1.55"


def test_dns_plugin_updates_capability_runtime() -> None:
    config = DNSConfig(
        servers=[
            DNSServerConfig(
                name="DNS-01",
                address="192.168.1.54",
            ),
            DNSServerConfig(
                name="DNS-02",
                address="192.168.1.55",
            ),
        ],
        policy=DNSPolicyConfig(minimum_healthy_servers=1),
    )

    plugin = DNSPlugin(config=config)

    plugin.servers[0].runtime.record_success(
        hostname="openai.com",
        address="104.18.32.47",
    )
    plugin.servers[1].runtime.record_failure(
        hostname="openai.com",
        error="timeout",
    )

    runtime = plugin.update_capability_runtime()

    assert runtime.total_servers == 2
    assert runtime.healthy_servers == 1
    assert runtime.failed_servers == 1
    assert runtime.healthy is True


def test_dns_plugin_updates_capability_runtime_with_strict_policy() -> None:
    config = DNSConfig(
        servers=[
            DNSServerConfig(
                name="DNS-01",
                address="192.168.1.54",
            ),
            DNSServerConfig(
                name="DNS-02",
                address="192.168.1.55",
            ),
        ],
        policy=DNSPolicyConfig(minimum_healthy_servers=2),
    )

    plugin = DNSPlugin(config=config)

    plugin.servers[0].runtime.record_success(
        hostname="openai.com",
        address="104.18.32.47",
    )
    plugin.servers[1].runtime.record_failure(
        hostname="openai.com",
        error="timeout",
    )

    runtime = plugin.update_capability_runtime()

    assert runtime.total_servers == 2
    assert runtime.healthy_servers == 1
    assert runtime.failed_servers == 1
    assert runtime.healthy is False


def test_dns_plugin_check_all_checks_enabled_servers_queries() -> None:
    config = DNSConfig(
        servers=[
            DNSServerConfig(
                name="DNS-01",
                address="192.168.1.54",
            ),
            DNSServerConfig(
                name="DNS-02",
                address="192.168.1.55",
            ),
        ],
        queries=["openai.com", "github.com"],
    )

    plugin = DNSPlugin(config=config)

    plugin.servers[0]._check = FakeDNSCheck(
        DNSCheckResult(
            hostname="openai.com",
            healthy=True,
            address="104.18.32.47",
        )
    )
    plugin.servers[1]._check = FakeDNSCheck(
        DNSCheckResult(
            hostname="openai.com",
            healthy=True,
            address="104.18.32.47",
        )
    )

    runtime = plugin.check_all()

    assert runtime.total_servers == 2
    assert runtime.healthy_servers == 2
    assert runtime.failed_servers == 0
    assert runtime.healthy is True
    assert plugin.servers[0].runtime.total_checks == 2
    assert plugin.servers[1].runtime.total_checks == 2


def test_dns_plugin_check_all_ignores_disabled_servers() -> None:
    config = DNSConfig(
        servers=[
            DNSServerConfig(
                name="DNS-01",
                address="192.168.1.54",
            ),
            DNSServerConfig(
                name="DNS-02",
                address="192.168.1.55",
                enabled=False,
            ),
        ],
        queries=["openai.com"],
    )

    plugin = DNSPlugin(config=config)

    plugin.servers[0]._check = FakeDNSCheck(
        DNSCheckResult(
            hostname="openai.com",
            healthy=True,
            address="104.18.32.47",
        )
    )
    plugin.servers[1]._check = FakeDNSCheck(
        DNSCheckResult(
            hostname="openai.com",
            healthy=False,
            error="should not run",
        )
    )

    runtime = plugin.check_all()

    assert runtime.total_servers == 2
    assert runtime.healthy_servers == 1
    assert runtime.failed_servers == 1
    assert runtime.healthy is True
    assert plugin.servers[0].runtime.total_checks == 1
    assert plugin.servers[1].runtime.total_checks == 0


def test_dns_plugin_check_all_uses_each_server_address() -> None:
    config = DNSConfig(
        servers=[
            DNSServerConfig(
                name="DNS-01",
                address="192.168.1.54",
            ),
            DNSServerConfig(
                name="DNS-02",
                address="192.168.1.55",
            ),
        ],
        queries=["openai.com"],
    )

    plugin = DNSPlugin(config=config)

    plugin.servers[0]._check = FakeDNSCheck(
        DNSCheckResult(
            hostname="openai.com",
            server="192.168.1.54",
            healthy=True,
            address="104.18.32.47",
        )
    )
    plugin.servers[1]._check = FakeDNSCheck(
        DNSCheckResult(
            hostname="openai.com",
            server="192.168.1.55",
            healthy=True,
            address="104.18.32.47",
        )
    )

    runtime = plugin.check_all()

    assert plugin.servers[0]._check.server == "192.168.1.54"
    assert plugin.servers[1]._check.server == "192.168.1.55"
    assert runtime.total_servers == 2
    assert runtime.healthy_servers == 2
    assert runtime.failed_servers == 0
    assert runtime.healthy is True


def test_dns_plugin_execute_returns_observer_result() -> None:
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="example.com",
            healthy=True,
            address="93.184.216.34",
        )
    )
    plugin = DNSPlugin(check=dns_check)

    result = plugin.execute(hostname="example.com")

    assert result.metadata == {
        "hostname": "example.com",
        "server": None,
        "address": "93.184.216.34",
        "error": None,
    }


def test_dns_plugin_execute_returns_failed_observer_result() -> None:
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="missing.local",
            healthy=False,
            error="host not found",
        )
    )
    plugin = DNSPlugin(check=dns_check)

    result = plugin.execute(hostname="missing.local")

    assert result.success is False
    assert result.check == "dns.resolve"
    assert result.message == "host not found"
    assert result.metadata["hostname"] == "missing.local"
    assert result.metadata["error"] == "host not found"


def test_dns_plugin_execute_requires_hostname() -> None:
    plugin = DNSPlugin()

    with pytest.raises(
        ValueError,
        match="requires a non-empty 'hostname' argument",
    ):
        plugin.execute()


def test_dns_plugin_executes_against_task_server() -> None:
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="example.com",
            server="192.168.1.12",
            healthy=True,
            address="93.184.216.34",
        )
    )
    plugin = DNSPlugin(check=dns_check)

    plugin.execute(
        hostname="example.com",
        server="192.168.1.12",
        service_id="dns-secondary",
    )

    assert dns_check.server == "192.168.1.12"


def test_dns_plugin_can_be_reconfigured() -> None:
    plugin = DNSPlugin()
    config = DNSConfig(
        servers=[
            DNSServerConfig(
                name="dns-secondary",
                address="192.168.1.12",
            )
        ],
        queries=["example.com"],
    )

    plugin.reconfigure(config)

    assert plugin.config is config
    assert [server.name for server in plugin.servers] == ["dns-secondary"]
