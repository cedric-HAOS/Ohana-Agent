from ohana_agent.plugins.dns.check_result import DNSCheckResult
from ohana_agent.plugins.dns.config import DNSServerConfig
from ohana_agent.plugins.dns.server import DNSServer
from ohana_agent.plugins.dns.server_runtime import DNSServerRuntime


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


def test_dns_server_exposes_config_values() -> None:
    server = DNSServer(
        DNSServerConfig(
            name="DNS-01",
            address="192.168.1.54",
        )
    )

    assert server.name == "DNS-01"
    assert server.address == "192.168.1.54"
    assert server.enabled is True


def test_dns_server_can_be_disabled_from_config() -> None:
    server = DNSServer(
        DNSServerConfig(
            name="DNS-02",
            address="192.168.1.55",
            enabled=False,
        )
    )

    assert server.name == "DNS-02"
    assert server.address == "192.168.1.55"
    assert server.enabled is False


def test_dns_server_has_runtime() -> None:
    server = DNSServer(
        DNSServerConfig(
            name="DNS-01",
            address="192.168.1.54",
        )
    )

    assert isinstance(server.runtime, DNSServerRuntime)


def test_dns_server_accepts_injected_runtime() -> None:
    runtime = DNSServerRuntime()

    server = DNSServer(
        config=DNSServerConfig(
            name="DNS-01",
            address="192.168.1.54",
        ),
        runtime=runtime,
    )

    assert server.runtime is runtime


def test_dns_server_check_records_success() -> None:
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="openai.com",
            healthy=True,
            address="104.18.32.47",
        )
    )

    server = DNSServer(
        config=DNSServerConfig(
            name="DNS-01",
            address="192.168.1.54",
        ),
        check=dns_check,
    )

    result = server.check("openai.com")

    assert dns_check.hostname == "openai.com"
    assert result.healthy is True
    assert server.runtime.total_checks == 1
    assert server.runtime.successful_checks == 1
    assert server.runtime.failed_checks == 0
    assert server.runtime.last_hostname == "openai.com"
    assert server.runtime.last_address == "104.18.32.47"
    assert server.runtime.last_error is None
    assert server.runtime.healthy is True


def test_dns_server_check_records_failure() -> None:
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="openai.com",
            healthy=False,
            error="timeout",
        )
    )

    server = DNSServer(
        config=DNSServerConfig(
            name="DNS-01",
            address="192.168.1.54",
        ),
        check=dns_check,
    )

    result = server.check("openai.com")

    assert dns_check.hostname == "openai.com"
    assert result.healthy is False
    assert server.runtime.total_checks == 1
    assert server.runtime.successful_checks == 0
    assert server.runtime.failed_checks == 1
    assert server.runtime.last_hostname == "openai.com"
    assert server.runtime.last_address is None
    assert server.runtime.last_error == "timeout"
    assert server.runtime.healthy is False


def test_dns_server_check_uses_server_address() -> None:
    dns_check = FakeDNSCheck(
        DNSCheckResult(
            hostname="openai.com",
            server="192.168.1.54",
            healthy=True,
            address="104.18.32.47",
        )
    )

    server = DNSServer(
        config=DNSServerConfig(
            name="DNS-01",
            address="192.168.1.54",
        ),
        check=dns_check,
    )

    result = server.check("openai.com")

    assert dns_check.hostname == "openai.com"
    assert dns_check.server == "192.168.1.54"
    assert result.server == "192.168.1.54"
