import socket
from collections.abc import Callable
from ipaddress import ip_address

import dns.exception
import dns.resolver

from plugins.dns.dns_result import DNSResult

AddressResolver = Callable[..., list[tuple[object, ...]]]


class DNSResolver:
    """Resolve hostnames using an explicit DNS server when provided."""

    def __init__(
        self,
        address_resolver: AddressResolver = socket.getaddrinfo,
    ) -> None:
        self._address_resolver = address_resolver

    def resolve(
        self,
        hostname: str,
        server: str | None = None,
    ) -> DNSResult:
        try:
            resolver = dns.resolver.Resolver(configure=server is None)

            if server is not None:
                resolver.nameservers = [self._resolve_nameserver(server)]

            answers = resolver.resolve(hostname, "A")
            address = answers[0].to_text()
        except (dns.exception.DNSException, OSError, ValueError) as exc:
            return DNSResult(
                hostname=hostname,
                server=server,
                success=False,
                error=str(exc),
            )

        return DNSResult(
            hostname=hostname,
            server=server,
            success=True,
            address=address,
        )

    def _resolve_nameserver(self, server: str) -> str:
        """Convert a DNS server hostname to the IP form required by dnspython."""
        normalized = server.strip()
        if not normalized:
            raise ValueError("DNS server must not be empty")

        if normalized.lower().startswith("https://"):
            return normalized

        try:
            ip_address(normalized)
        except ValueError:
            addresses = self._address_resolver(
                normalized,
                53,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_DGRAM,
            )
            for address_info in addresses:
                socket_address = address_info[4]
                if (
                    isinstance(socket_address, tuple)
                    and socket_address
                    and isinstance(socket_address[0], str)
                ):
                    return socket_address[0]

            raise OSError(
                f"DNS server hostname {normalized!r} has no IP address"
            ) from None

        return normalized
