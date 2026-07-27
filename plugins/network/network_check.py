"""Network presence check with retry support."""

from plugins.network.network_probe_result import NetworkProbeResult
from plugins.network.system_network_probe import SystemNetworkProbe


class NetworkCheck:
    """Check whether one network address is currently reachable."""

    def __init__(self, probe: SystemNetworkProbe | None = None) -> None:
        self._probe = probe or SystemNetworkProbe()

    def check(
        self,
        address: str,
        *,
        timeout: float = 1.0,
        retries: int = 0,
    ) -> NetworkProbeResult:
        """Probe until the address is reached or attempts are exhausted."""
        if retries < 0:
            raise ValueError("retries must be greater than or equal to zero.")

        last_result: NetworkProbeResult | None = None
        attempts = 0

        for _attempt in range(retries + 1):
            attempts += 1
            last_result = self._probe.probe(address, timeout=timeout)

            if last_result.reachable is not False:
                break

        if last_result is None:
            raise RuntimeError("Network check did not execute any probe.")

        return NetworkProbeResult(
            address=last_result.address,
            reachable=last_result.reachable,
            method=last_result.method,
            latency_ms=last_result.latency_ms,
            attempts=attempts,
            error=last_result.error,
        )
