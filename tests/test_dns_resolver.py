import socket

import dns.exception
import dns.resolver

from plugins.dns.dns_resolver import DNSResolver


class FakeAnswer:
    def __init__(self, address: str) -> None:
        self.address = address

    def to_text(self) -> str:
        return self.address


class FakeResolver:
    last_instance: "FakeResolver | None" = None

    def __init__(self, configure: bool) -> None:
        self.configure = configure
        self.nameservers: list[str] = []
        FakeResolver.last_instance = self

    def resolve(self, hostname: str, record_type: str) -> list[FakeAnswer]:
        assert hostname == "example.com"
        assert record_type == "A"
        return [FakeAnswer("93.184.216.34")]


class FailingResolver(FakeResolver):
    def resolve(self, hostname: str, record_type: str) -> list[FakeAnswer]:
        assert hostname == "missing.local"
        assert record_type == "A"
        raise dns.exception.DNSException("host not found")


def test_dns_resolver_returns_success(monkeypatch) -> None:
    monkeypatch.setattr(dns.resolver, "Resolver", FakeResolver)

    resolver = DNSResolver()

    result = resolver.resolve(
        hostname="example.com",
        server="192.168.1.54",
    )

    assert result.server == "192.168.1.54"
    assert result.hostname == "example.com"
    assert result.success is True
    assert result.address == "93.184.216.34"
    assert result.error is None


def test_dns_resolver_resolves_nameserver_hostname_before_query(monkeypatch) -> None:
    monkeypatch.setattr(dns.resolver, "Resolver", FakeResolver)
    calls: list[tuple[str, int, int, int]] = []

    def resolve_address(
        hostname: str,
        port: int,
        *,
        family: int,
        type: int,
    ) -> list[tuple[object, ...]]:
        calls.append((hostname, port, family, type))
        return [
            (
                socket.AF_INET,
                socket.SOCK_DGRAM,
                socket.IPPROTO_UDP,
                "",
                ("192.168.1.11", 53),
            )
        ]

    resolver = DNSResolver(address_resolver=resolve_address)

    result = resolver.resolve(
        hostname="example.com",
        server="zwave-01.ohana.lan",
    )

    assert result.success is True
    assert result.server == "zwave-01.ohana.lan"
    assert calls == [
        (
            "zwave-01.ohana.lan",
            53,
            socket.AF_UNSPEC,
            socket.SOCK_DGRAM,
        )
    ]
    assert FakeResolver.last_instance is not None
    assert FakeResolver.last_instance.nameservers == ["192.168.1.11"]


def test_dns_resolver_returns_failure_when_nameserver_hostname_is_unknown(
    monkeypatch,
) -> None:
    monkeypatch.setattr(dns.resolver, "Resolver", FakeResolver)

    def fail_resolution(*_args, **_kwargs):
        raise socket.gaierror("nameserver not found")

    resolver = DNSResolver(address_resolver=fail_resolution)

    result = resolver.resolve(
        hostname="example.com",
        server="missing.ohana.lan",
    )

    assert result.success is False
    assert result.server == "missing.ohana.lan"
    assert result.error == "nameserver not found"


def test_dns_resolver_returns_failure(monkeypatch) -> None:
    monkeypatch.setattr(dns.resolver, "Resolver", FailingResolver)

    resolver = DNSResolver()

    result = resolver.resolve(
        hostname="missing.local",
        server="192.168.1.55",
    )

    assert result.server == "192.168.1.55"
    assert result.hostname == "missing.local"
    assert result.success is False
    assert result.address is None
    assert result.error == "host not found"


def test_dns_resolver_accepts_no_explicit_server(monkeypatch) -> None:
    monkeypatch.setattr(dns.resolver, "Resolver", FakeResolver)

    resolver = DNSResolver()

    result = resolver.resolve("example.com")

    assert result.hostname == "example.com"
    assert result.server is None
    assert result.success is True
    assert result.address == "93.184.216.34"
    assert result.error is None
