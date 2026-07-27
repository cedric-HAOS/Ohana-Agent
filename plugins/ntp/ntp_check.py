"""NTP capability check with retry support."""

from plugins.ntp.ntp_check_result import NTPCheckResult
from plugins.ntp.ntp_client import NTPClient


class NTPCheck:
    """Check an NTP server by performing an SNTP query."""

    def __init__(self, client: NTPClient | None = None) -> None:
        self._client = client or NTPClient()

    def check(
        self,
        server: str,
        *,
        port: int = 123,
        timeout: float = 2.0,
        retries: int = 1,
    ) -> NTPCheckResult:
        """Query a server until it succeeds or retries are exhausted."""
        if retries < 0:
            raise ValueError("retries must be greater than or equal to zero.")

        last_result = None
        attempts = 0

        for _attempt in range(retries + 1):
            attempts += 1
            last_result = self._client.query(
                server,
                port=port,
                timeout=timeout,
            )

            if last_result.success:
                break

        if last_result is None:
            raise RuntimeError("NTP check did not execute any request.")

        return NTPCheckResult(
            server=last_result.server,
            port=last_result.port,
            healthy=last_result.success,
            source_address=last_result.source_address,
            offset_ms=last_result.offset_ms,
            round_trip_ms=last_result.round_trip_ms,
            stratum=last_result.stratum,
            version=last_result.version,
            leap_indicator=last_result.leap_indicator,
            attempts=attempts,
            error=last_result.error,
        )
