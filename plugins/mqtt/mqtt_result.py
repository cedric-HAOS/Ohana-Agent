"""Raw result returned by the MQTT round-trip client."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MQTTResult:
    """Result of one MQTT publish and receive round trip."""

    broker: str
    port: int
    success: bool
    topic: str | None = None
    qos: int | None = None
    client_id: str | None = None
    connected: bool = False
    subscribed: bool = False
    published: bool = False
    received: bool = False
    round_trip_ms: float | None = None
    tls_enabled: bool = False
    error: str | None = None
