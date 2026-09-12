from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MQTTReconnectPolicy:
    """Compute reconnect delays for MQTT connection retries."""

    enabled: bool = True
    initial_delay_seconds: int = 1
    max_delay_seconds: int = 30

    def __post_init__(self) -> None:
        if self.initial_delay_seconds <= 0:
            raise ValueError("initial_delay_seconds must be greater than 0.")

        if self.max_delay_seconds <= 0:
            raise ValueError("max_delay_seconds must be greater than 0.")

        if self.initial_delay_seconds > self.max_delay_seconds:
            raise ValueError(
                "initial_delay_seconds must be less than or equal to max_delay_seconds."
            )

    def get_delay(self, attempt: int) -> int:
        """Return delay in seconds for a retry attempt.

        attempt is zero-based:
        - attempt 0 -> initial delay
        - attempt 1 -> initial delay * 2
        - attempt 2 -> initial delay * 4
        """

        if attempt < 0:
            raise ValueError("attempt must be greater than or equal to 0.")

        if not self.enabled:
            return 0

        delay = self.initial_delay_seconds * (2**attempt)

        return min(delay, self.max_delay_seconds)

    def should_retry(self) -> bool:
        """Return whether reconnect attempts are enabled."""

        return self.enabled

    def delays(self, attempts: int) -> list[int]:
        """Return reconnect delays for a number of attempts."""

        if attempts < 0:
            raise ValueError("attempts must be greater than or equal to 0.")

        return [self.get_delay(attempt) for attempt in range(attempts)]
