"""Small HTTP client for the Z-Wave JS UI health endpoint."""

from __future__ import annotations

import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from plugins.zwave.zwave_result import ZWaveHealthResult


class ZWaveHealthClient:
    """Query the public Z-Wave JS UI health endpoint."""

    def query(
        self,
        url: str,
        *,
        timeout: float = 3.0,
        verify_tls: bool = True,
    ) -> ZWaveHealthResult:
        """Return the HTTP health reported by Z-Wave JS UI."""
        request = Request(
            url,
            headers={
                "Accept": "text/plain, application/json",
                "User-Agent": "Ohana-Agent Z-Wave health check",
            },
        )
        context = None

        if url.lower().startswith("https://") and not verify_tls:
            context = ssl._create_unverified_context()

        try:
            with urlopen(request, timeout=timeout, context=context) as response:
                status_code = int(response.status)
                body = (
                    response.read(4096)
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                    .strip()
                )
                return ZWaveHealthResult(
                    url=url,
                    healthy=status_code == 200,
                    status_code=status_code,
                    response=body or None,
                    error=(
                        None
                        if status_code == 200
                        else (f"Z-Wave health endpoint returned HTTP {status_code}.")
                    ),
                )
        except HTTPError as error:
            body = (
                error.read(4096)
                .decode(
                    "utf-8",
                    errors="replace",
                )
                .strip()
            )
            return ZWaveHealthResult(
                url=url,
                healthy=False,
                status_code=error.code,
                response=body or None,
                error=(f"Z-Wave health endpoint returned HTTP {error.code}."),
            )
        except (URLError, TimeoutError, OSError) as error:
            return ZWaveHealthResult(
                url=url,
                healthy=False,
                error=str(error),
            )
