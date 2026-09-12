from dataclasses import dataclass


@dataclass
class DNSServerRuntime:
    """Runtime state for one DNS server."""

    total_checks: int = 0
    successful_checks: int = 0
    failed_checks: int = 0
    last_hostname: str | None = None
    last_address: str | None = None
    last_error: str | None = None
    healthy: bool | None = None

    def record_success(self, hostname: str, address: str | None) -> None:
        self.total_checks += 1
        self.successful_checks += 1
        self.last_hostname = hostname
        self.last_address = address
        self.last_error = None
        self.healthy = True

    def record_failure(self, hostname: str, error: str | None) -> None:
        self.total_checks += 1
        self.failed_checks += 1
        self.last_hostname = hostname
        self.last_address = None
        self.last_error = error
        self.healthy = False
