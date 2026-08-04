"""Results exposed by the Z-Wave health check and node discovery."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ZWaveNodeResult:
    """Stable discovery data for one Z-Wave JS node."""

    node_id: int
    status: str
    ready: bool = False
    name: str | None = None
    label: str | None = None
    location: str | None = None
    manufacturer: str | None = None
    product_id: int | str | None = None
    product_type: int | str | None = None
    firmware_version: str | None = None
    can_sleep: bool = False
    last_seen: str | None = None

    @property
    def alive(self) -> bool | None:
        """Return the operational state without treating sleep as a failure."""
        normalized = self.status.strip().lower()

        if normalized in {"alive", "awake", "asleep"}:
            return True

        if normalized == "dead":
            return False

        return None


@dataclass(frozen=True, slots=True)
class ZWaveHealthResult:
    """Result of one Z-Wave JS health request."""

    url: str
    healthy: bool
    status_code: int | None = None
    response: str | None = None
    server_version: str | None = None
    driver_version: str | None = None
    home_id: str | None = None
    node_count: int | None = None
    nodes: tuple[ZWaveNodeResult, ...] = ()
    discovery_complete: bool = False
    attempts: int = 1
    error: str | None = None
