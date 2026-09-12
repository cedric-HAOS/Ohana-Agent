from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class MQTTTransportState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"


class MQTTTransportError(Exception):
    """Base exception for MQTT transport errors."""


class MQTTTransportNotConnectedError(MQTTTransportError):
    """Raised when transport operation requires an active connection."""


@dataclass(frozen=True)
class MQTTLastWill:
    topic: str
    payload: str
    qos: int = 1
    retain: bool = True


class MQTTNetworkBackend(Protocol):
    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def publish(
        self,
        topic: str,
        payload: str,
        *,
        qos: int,
        retain: bool,
    ) -> None: ...

    async def subscribe(self, topic: str) -> None: ...

    async def unsubscribe(self, topic: str) -> None: ...


class MQTTTransport:
    """Transport layer between MQTT runtime and network backend."""

    def __init__(
        self,
        backend: MQTTNetworkBackend,
        *,
        last_will: MQTTLastWill | None = None,
    ) -> None:
        self.backend = backend
        self.last_will = last_will
        self.state = MQTTTransportState.DISCONNECTED

    @property
    def is_connected(self) -> bool:
        return self.state == MQTTTransportState.CONNECTED

    async def connect(self) -> None:
        if self.is_connected:
            return

        self.state = MQTTTransportState.CONNECTING

        try:
            await self.backend.connect()
            self.state = MQTTTransportState.CONNECTED
        except Exception:
            self.state = MQTTTransportState.DISCONNECTED
            raise

    async def disconnect(self) -> None:
        if not self.is_connected:
            self.state = MQTTTransportState.DISCONNECTED
            return

        self.state = MQTTTransportState.DISCONNECTING

        try:
            await self.backend.disconnect()
        finally:
            self.state = MQTTTransportState.DISCONNECTED

    async def publish(
        self,
        topic: str,
        payload: str,
        *,
        qos: int,
        retain: bool,
    ) -> None:
        self._ensure_connected()

        await self.backend.publish(
            topic,
            payload,
            qos=qos,
            retain=retain,
        )

    async def subscribe(self, topic: str) -> None:
        self._ensure_connected()

        await self.backend.subscribe(topic)

    async def unsubscribe(self, topic: str) -> None:
        self._ensure_connected()

        await self.backend.unsubscribe(topic)

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            raise MQTTTransportNotConnectedError("MQTT transport is not connected.")
