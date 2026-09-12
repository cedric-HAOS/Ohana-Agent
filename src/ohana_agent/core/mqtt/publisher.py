from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Protocol


class MQTTBackendPublisher(Protocol):
    async def publish(
        self,
        topic: str,
        payload: str,
        *,
        qos: int,
        retain: bool,
    ) -> None: ...


class MQTTPublisher:
    """Serialize and publish MQTT messages."""

    def __init__(self, backend: MQTTBackendPublisher) -> None:
        self.backend = backend

    async def publish(
        self,
        topic: str,
        payload: object,
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        serialized_payload = self.serialize(payload)

        await self.backend.publish(
            topic,
            serialized_payload,
            qos=qos,
            retain=retain,
        )

    def serialize(self, payload: object) -> str:
        normalized = self._normalize(payload)

        return json.dumps(normalized, ensure_ascii=False)

    def _normalize(self, payload: object) -> Any:
        if is_dataclass(payload) and not isinstance(payload, type):
            return asdict(payload)

        if isinstance(payload, Enum):
            return payload.value

        if isinstance(payload, dict):
            return {str(key): self._normalize(value) for key, value in payload.items()}

        if isinstance(payload, list | tuple | set):
            return [self._normalize(value) for value in payload]

        if isinstance(payload, datetime):
            return payload.isoformat()

        return payload
