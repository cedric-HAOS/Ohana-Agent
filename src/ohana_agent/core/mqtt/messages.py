from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class MQTTAvailabilityStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"


class MQTTHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True)
class MQTTAvailabilityMessage:
    status: MQTTAvailabilityStatus

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.status.value,
        }


@dataclass(frozen=True)
class MQTTStatusMessage:
    agent: str
    state: str
    health: MQTTHealthStatus
    uptime: int
    version: str
    timestamp: str

    @classmethod
    def create(
        cls,
        *,
        agent: str,
        state: str,
        health: MQTTHealthStatus,
        uptime: int,
        version: str,
    ) -> MQTTStatusMessage:
        return cls(
            agent=agent,
            state=state,
            health=health,
            uptime=uptime,
            version=version,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "agent": self.agent,
            "state": self.state,
            "health": self.health.value,
            "uptime": self.uptime,
            "version": self.version,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class MQTTCommandMessage:
    command: str
    correlation_id: str | None = None
    payload: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "command": self.command,
        }

        if self.correlation_id is not None:
            data["correlation_id"] = self.correlation_id

        if self.payload is not None:
            data["payload"] = self.payload

        return data


@dataclass(frozen=True)
class MQTTEventMessage:
    event_type: str
    payload: dict[str, object]
    timestamp: str

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        payload: dict[str, object],
    ) -> MQTTEventMessage:
        return cls(
            event_type=event_type,
            payload=payload,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "event_type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }
