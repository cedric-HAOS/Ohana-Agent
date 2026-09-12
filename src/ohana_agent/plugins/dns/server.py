from ohana_agent.plugins.dns.check import DNSCheck
from ohana_agent.plugins.dns.check_result import DNSCheckResult
from ohana_agent.plugins.dns.config import DNSServerConfig
from ohana_agent.plugins.dns.server_runtime import DNSServerRuntime


class DNSServer:
    """DNS server managed by the DNS plugin."""

    def __init__(
        self,
        config: DNSServerConfig,
        runtime: DNSServerRuntime | None = None,
        check: DNSCheck | None = None,
    ) -> None:
        self.config = config
        self.runtime = runtime or DNSServerRuntime()
        self._check = check or DNSCheck()

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def address(self) -> str:
        return self.config.address

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def check(self, hostname: str) -> DNSCheckResult:
        result = self._check.check(
            hostname=hostname,
            server=self.address,
        )

        if result.healthy:
            self.runtime.record_success(
                hostname=result.hostname,
                address=result.address,
            )
        else:
            self.runtime.record_failure(
                hostname=result.hostname,
                error=result.error,
            )

        return result
