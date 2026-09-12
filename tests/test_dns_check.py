from dataclasses import dataclass

from ohana_agent.observation.checks import DNSCheck


@dataclass(slots=True)
class FakeDNSResult:
    hostname: str
    success: bool
    server: str
    address: str | None
    error: str | None
    latency: float


class FakeDNSResolver:
    def __init__(self, result: FakeDNSResult) -> None:
        self.result = result
        self.hostname: str | None = None
        self.server: str | None = None

    def resolve(self, hostname: str, server: str) -> FakeDNSResult:
        self.hostname = hostname
        self.server = server
        return self.result


def test_dns_check_stores_hostname() -> None:
    resolver = FakeDNSResolver(
        FakeDNSResult(
            hostname="example.com",
            success=True,
            server="192.168.1.54",
            address="93.184.216.34",
            error=None,
            latency=12.0,
        )
    )

    check = DNSCheck(
        hostname="example.com",
        server="192.168.1.54",
        resolver=resolver,
    )

    assert check.hostname == "example.com"


def test_dns_check_stores_server() -> None:
    resolver = FakeDNSResolver(
        FakeDNSResult(
            hostname="example.com",
            success=True,
            server="192.168.1.54",
            address="93.184.216.34",
            error=None,
            latency=12.0,
        )
    )

    check = DNSCheck(
        hostname="example.com",
        server="192.168.1.54",
        resolver=resolver,
    )

    assert check.server == "192.168.1.54"


def test_dns_check_calls_resolver() -> None:
    resolver = FakeDNSResolver(
        FakeDNSResult(
            hostname="example.com",
            success=True,
            server="192.168.1.54",
            address="93.184.216.34",
            error=None,
            latency=12.0,
        )
    )

    check = DNSCheck(
        hostname="example.com",
        server="192.168.1.54",
        resolver=resolver,
    )

    check.execute()

    assert resolver.hostname == "example.com"
    assert resolver.server == "192.168.1.54"


def test_dns_check_returns_success_result() -> None:
    resolver = FakeDNSResolver(
        FakeDNSResult(
            hostname="example.com",
            success=True,
            server="192.168.1.54",
            address="93.184.216.34",
            error=None,
            latency=12.0,
        )
    )

    check = DNSCheck(
        hostname="example.com",
        server="192.168.1.54",
        resolver=resolver,
    )

    result = check.execute()

    assert result.success is True
    assert result.latency == 12.0
    assert result.message is None


def test_dns_check_returns_failure_result() -> None:
    resolver = FakeDNSResolver(
        FakeDNSResult(
            hostname="example.com",
            success=False,
            server="192.168.1.54",
            address=None,
            error="DNS resolution failed",
            latency=42.0,
        )
    )

    check = DNSCheck(
        hostname="example.com",
        server="192.168.1.54",
        resolver=resolver,
    )

    result = check.execute()

    assert result.failed is True
    assert result.latency == 42.0
    assert result.message == "DNS resolution failed"


def test_dns_check_adds_metadata() -> None:
    resolver = FakeDNSResolver(
        FakeDNSResult(
            hostname="example.com",
            success=True,
            server="192.168.1.54",
            address="93.184.216.34",
            error=None,
            latency=12.0,
        )
    )

    check = DNSCheck(
        hostname="example.com",
        server="192.168.1.54",
        resolver=resolver,
    )

    result = check.execute()

    assert result.metadata == {
        "hostname": "example.com",
        "server": "192.168.1.54",
        "address": "93.184.216.34",
    }


def test_dns_check_has_name() -> None:
    resolver = FakeDNSResolver(
        FakeDNSResult(
            hostname="example.com",
            success=True,
            server="192.168.1.54",
            address="93.184.216.34",
            error=None,
            latency=12.0,
        )
    )

    check = DNSCheck(
        hostname="example.com",
        server="192.168.1.54",
        resolver=resolver,
    )

    assert check.name == "dns.resolve"


def test_dns_check_has_description() -> None:
    resolver = FakeDNSResolver(
        FakeDNSResult(
            hostname="example.com",
            success=True,
            server="192.168.1.54",
            address="93.184.216.34",
            error=None,
            latency=12.0,
        )
    )

    check = DNSCheck(
        hostname="example.com",
        server="192.168.1.54",
        resolver=resolver,
    )

    assert check.description == "Resolve example.com using 192.168.1.54"


def test_dns_check_adds_check_name_to_result() -> None:
    resolver = FakeDNSResolver(
        FakeDNSResult(
            hostname="example.com",
            success=True,
            server="192.168.1.54",
            address="93.184.216.34",
            error=None,
            latency=12.0,
        )
    )

    check = DNSCheck(
        hostname="example.com",
        server="192.168.1.54",
        resolver=resolver,
    )

    result = check.execute()

    assert result.check == "dns.resolve"


def test_dns_check_adds_description_to_result() -> None:
    resolver = FakeDNSResolver(
        FakeDNSResult(
            hostname="example.com",
            success=True,
            server="192.168.1.54",
            address="93.184.216.34",
            error=None,
            latency=12.0,
        )
    )

    check = DNSCheck(
        hostname="example.com",
        server="192.168.1.54",
        resolver=resolver,
    )

    result = check.execute()

    assert result.description == "Resolve example.com using 192.168.1.54"
