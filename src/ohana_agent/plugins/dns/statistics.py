# plugins/dns/dns_statistics.py

from dataclasses import dataclass

from ohana_agent.plugins.dns.runtime import DNSRuntime


@dataclass(frozen=True)
class DNSStatistics:
    """Statistics snapshot for the DNS plugin."""

    total_checks: int
    successful_checks: int
    failed_checks: int
    success_rate: float
    healthy: bool | None

    @classmethod
    def from_runtime(cls, runtime: DNSRuntime) -> "DNSStatistics":
        success_rate = 0.0

        if runtime.total_checks > 0:
            success_rate = runtime.successful_checks / runtime.total_checks

        return cls(
            total_checks=runtime.total_checks,
            successful_checks=runtime.successful_checks,
            failed_checks=runtime.failed_checks,
            success_rate=success_rate,
            healthy=runtime.healthy,
        )
