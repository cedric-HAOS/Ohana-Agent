"""HTTP client used to send data to Ohana-Vision."""

import json
from dataclasses import dataclass
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ohana_agent.observation.exporters.vision_client_error import VisionClientError


@dataclass(frozen=True, slots=True)
class HttpVisionClient:
    """Send observation and infrastructure payloads to Ohana-Vision."""

    observation_url: str
    infrastructure_url: str = "http://127.0.0.1:8000/api/infrastructure"
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        """Validate client configuration."""
        if not self.observation_url.strip():
            raise ValueError("observation_url must not be empty.")

        if not self.infrastructure_url.strip():
            raise ValueError("infrastructure_url must not be empty.")

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")

    def send_observation(
        self,
        payload: dict[str, Any],
    ) -> None:
        """Send one observation payload to Ohana-Vision."""
        self._send_payload(
            payload=payload,
            url=self.observation_url,
            method="POST",
            expected_status=202,
            payload_name="observation",
        )

    def send_infrastructure(
        self,
        payload: dict[str, Any],
    ) -> None:
        """Send one infrastructure snapshot to Ohana-Vision."""
        self._send_payload(
            payload=payload,
            url=self.infrastructure_url,
            method="PUT",
            expected_status=200,
            payload_name="infrastructure snapshot",
        )

    def _send_payload(
        self,
        *,
        payload: dict[str, Any],
        url: str,
        method: Literal["POST", "PUT"],
        expected_status: int,
        payload_name: str,
    ) -> None:
        """Send one JSON payload and validate the HTTP response."""
        request = Request(
            url=url,
            data=self._encode_payload(
                payload,
                payload_name=payload_name,
            ),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method=method,
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                status_code = response.status

        except HTTPError as error:
            response_body = self._read_error_body(error)

            raise VisionClientError(
                self._build_http_error_message(
                    payload_name=payload_name,
                    status_code=error.code,
                    response_body=response_body,
                )
            ) from error

        except URLError as error:
            raise VisionClientError(
                f"Unable to reach Ohana-Vision at {url}: {error.reason}"
            ) from error

        except TimeoutError as error:
            raise VisionClientError(
                f"Timed out while sending the {payload_name} to Ohana-Vision at {url}."
            ) from error

        if status_code != expected_status:
            raise VisionClientError(
                "Ohana-Vision returned unexpected HTTP status "
                f"{status_code}; expected {expected_status}."
            )

    @staticmethod
    def _encode_payload(
        payload: dict[str, Any],
        *,
        payload_name: str,
    ) -> bytes:
        """Encode a payload as UTF-8 JSON."""
        try:
            serialized_payload = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as error:
            raise VisionClientError(
                f"The {payload_name} payload cannot be encoded as JSON."
            ) from error

        return serialized_payload.encode("utf-8")

    @staticmethod
    def _read_error_body(
        error: HTTPError,
    ) -> str:
        """Read an HTTP error response."""
        try:
            return error.read().decode(
                "utf-8",
                errors="replace",
            )
        except OSError:
            return ""

    @staticmethod
    def _build_http_error_message(
        *,
        payload_name: str,
        status_code: int,
        response_body: str,
    ) -> str:
        """Build a useful HTTP failure message."""
        message = (
            f"Ohana-Vision rejected the {payload_name} with HTTP status {status_code}."
        )

        if response_body:
            return f"{message} Response: {response_body}"

        return message
