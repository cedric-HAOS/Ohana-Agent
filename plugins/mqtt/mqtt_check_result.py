"""Result exposed by the MQTT capability check."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MQTTCheckResult:
    """Result of an MQTT round-trip capability check."""

    broker: str
    port: int
    healthy: bool
    topic: str | None = None
    qos: int | None = None
    client_id: str | None = None
    connected: bool = False
    subscribed: bool = False
    published: bool = False
    received: bool = False
    round_trip_ms: float | None = None
    tls_enabled: bool = False
    attempts: int = 1
    error: str | None = None
