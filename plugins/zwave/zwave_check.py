"""Z-Wave JS endpoint check with retry support."""

from plugins.zwave.zwave_client import ZWaveHealthClient
from plugins.zwave.zwave_result import ZWaveHealthResult


class ZWaveCheck:
    """Check whether one Z-Wave JS Server driver is connected."""

    def __init__(self, client: ZWaveHealthClient | None = None) -> None:
        self._client = client or ZWaveHealthClient()

    def check(
        self,
        url: str,
        *,
        timeout: float = 3.0,
        retries: int = 1,
        verify_tls: bool = True,
    ) -> ZWaveHealthResult:
        """Query the configured endpoint until it succeeds or retries are exhausted."""
        if retries < 0:
            raise ValueError("retries must be greater than or equal to zero.")

        last_result: ZWaveHealthResult | None = None
        attempts = 0

        for _attempt in range(retries + 1):
            attempts += 1
            last_result = self._client.query(
                url,
                timeout=timeout,
                verify_tls=verify_tls,
            )

            if last_result.healthy:
                break

        if last_result is None:
            raise RuntimeError("Z-Wave check did not execute any request.")

        return ZWaveHealthResult(
            url=last_result.url,
            healthy=last_result.healthy,
            status_code=last_result.status_code,
            response=last_result.response,
            server_version=last_result.server_version,
            driver_version=last_result.driver_version,
            home_id=last_result.home_id,
            node_count=last_result.node_count,
            attempts=attempts,
            error=last_result.error,
        )
