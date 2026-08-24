"""Optional native Shizune notifications delivered directly through APNs."""

from __future__ import annotations

import base64
import json
import logging
import queue
import time
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock, Thread
from typing import Any

from administration.companions import CompanionRepository
from configuration.administration import APNsConfig

LOGGER = logging.getLogger(__name__)
NOTIFICATION_TYPES = {
    "INFORMATION",
    "ATTENTION",
    "DECISION_REQUIRED",
    "CRITICAL",
    "RESOLVED",
}


class APNsDeliveryError(RuntimeError):
    """Raised for a rejected or unavailable APNs delivery."""


class APNsNotificationPublisher:
    """Send rare Shizune alerts without keeping an idle network connection."""

    def __init__(
        self,
        *,
        config: APNsConfig,
        companions: CompanionRepository,
        utc_now: Callable[[], datetime] | None = None,
        request_sender: Callable[[str, str, dict[str, Any], dict[str, str]], int]
        | None = None,
        provider_token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self.companions = companions
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._request_sender = request_sender or self._send_request
        self._provider_token_factory = provider_token_factory or self._provider_token
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100)
        self._thread_lock = Lock()
        self._thread: Thread | None = None
        self._published_ids: list[str] = []
        self._provider_token_value: str | None = None
        self._provider_token_created_at = 0

    @property
    def enabled(self) -> bool:
        """Return whether the Apple provider credentials are configured."""
        return self.config.enabled

    def publish(self, payload: dict[str, Any]) -> None:
        """Queue one allowlisted event and return immediately to Agent."""
        if not self.enabled:
            return
        notification = self._validated_notification(payload)
        notification_id = notification["notification_id"]
        with self._thread_lock:
            if notification_id in self._published_ids:
                return
            try:
                self._queue.put_nowait(notification)
            except queue.Full:
                LOGGER.warning(
                    "Shizune notification queue is full; dropping %s", notification_id
                )
                return
            self._published_ids.append(notification_id)
            del self._published_ids[:-256]
            if self._thread is None or not self._thread.is_alive():
                self._thread = Thread(
                    target=self._drain,
                    name="ohana-shizune-apns",
                    daemon=True,
                )
                self._thread.start()

    def wait_until_idle(self, timeout: float = 10.0) -> bool:
        """Wait for tests or orderly shutdown without keeping an idle worker."""
        with self._thread_lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        with self._thread_lock:
            return self._thread is None

    def _drain(self) -> None:
        while True:
            with self._thread_lock:
                try:
                    notification = self._queue.get_nowait()
                except queue.Empty:
                    self._thread = None
                    return
            self._deliver_with_retries(notification)
            self._queue.task_done()

    def _deliver_with_retries(self, notification: dict[str, Any]) -> None:
        targets = self.companions.push_targets(self.config.environment)
        if not targets:
            LOGGER.info("No Shizune APNs target is registered")
            return
        for device_id, device_token in targets:
            for attempt, delay in enumerate((0, 1, 5), start=1):
                if delay:
                    time.sleep(delay)
                try:
                    status = self._request_sender(
                        device_id,
                        device_token,
                        notification,
                        self._headers(),
                    )
                    if status == 200:
                        break
                    if status == 410:
                        self.companions.disable_push_token(device_id)
                        LOGGER.info("Disabled an APNs token rejected as unregistered")
                        break
                    raise APNsDeliveryError(f"APNs returned HTTP {status}")
                except Exception as error:
                    if attempt == 3:
                        LOGGER.warning(
                            "Unable to deliver Shizune notification %s: %s",
                            notification["notification_id"],
                            error,
                        )

    def _headers(self) -> dict[str, str]:
        return {
            "authorization": f"bearer {self._provider_token_factory()}",
            "apns-topic": self.config.bundle_id,
            "apns-push-type": "alert",
            "apns-priority": "10",
            "content-type": "application/json",
        }

    def _provider_token(self) -> str:
        now = int(self._utc_now().timestamp())
        if (
            self._provider_token_value is not None
            and now - self._provider_token_created_at < 50 * 60
        ):
            return self._provider_token_value
        if self.config.team_id is None or self.config.key_id is None:
            raise APNsDeliveryError("APNs provider identity is incomplete")
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives.asymmetric.utils import (
                decode_dss_signature,
            )
        except ImportError as error:
            raise APNsDeliveryError(
                "The cryptography dependency is unavailable"
            ) from error
        private_key = serialization.load_pem_private_key(
            self.config.private_key_file.read_bytes(), password=None
        )
        if not isinstance(private_key, ec.EllipticCurvePrivateKey):
            raise APNsDeliveryError("The APNs key is not an EC private key")
        header = self._base64url(
            json.dumps(
                {"alg": "ES256", "kid": self.config.key_id},
                separators=(",", ":"),
            ).encode("utf-8")
        )
        claims = self._base64url(
            json.dumps(
                {"iss": self.config.team_id, "iat": now},
                separators=(",", ":"),
            ).encode("utf-8")
        )
        signing_input = f"{header}.{claims}".encode("ascii")
        der_signature = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der_signature)
        signature = self._base64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        self._provider_token_value = f"{header}.{claims}.{signature}"
        self._provider_token_created_at = now
        return self._provider_token_value

    def _send_request(
        self,
        device_id: str,
        device_token: str,
        notification: dict[str, Any],
        headers: dict[str, str],
    ) -> int:
        del device_id
        try:
            import httpx
        except ImportError as error:
            raise APNsDeliveryError(
                "The httpx HTTP/2 dependency is unavailable"
            ) from error
        host = (
            "api.development.push.apple.com"
            if self.config.environment == "development"
            else "api.push.apple.com"
        )
        document = {
            "aps": {
                "alert": {
                    "title": notification["title"],
                    "body": notification["message"],
                },
                "sound": "default",
                "thread-id": "tsunade",
            },
            "ohana": {
                "type": notification["type"],
                "incident_id": notification.get("incident_id"),
                "notification_id": notification["notification_id"],
            },
        }
        with httpx.Client(http2=True, timeout=self.config.timeout_seconds) as client:
            response = client.post(
                f"https://{host}/3/device/{device_token}",
                headers=headers,
                json=document,
            )
        return response.status_code

    def _validated_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        notification_id = str(payload.get("notification_id") or "")[:160]
        notification_type = str(payload.get("type") or "").upper()
        title = str(payload.get("title") or "Tsunade")[:160]
        message = str(payload.get("message") or "")[:1000]
        if (
            not notification_id
            or notification_type not in NOTIFICATION_TYPES
            or not message
        ):
            raise ValueError("Invalid Shizune notification payload")
        return {
            "notification_id": notification_id,
            "type": notification_type,
            "title": title,
            "message": message,
            "incident_id": payload.get("incident_id"),
            "occurred_at": payload.get("occurred_at") or self._utc_now().isoformat(),
        }

    @staticmethod
    def _base64url(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
