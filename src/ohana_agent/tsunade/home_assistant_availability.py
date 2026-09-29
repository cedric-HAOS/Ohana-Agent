"""Phase 4 hardening: hourly count of unavailable Home Assistant entities.

One read of ``/api/states`` per hour with the telemetry plugin's access. Only
the number of ``unavailable`` entities and their identifiers are kept (no
state values); the preventive rule compares the daily minimum, which ignores
the minute Home Assistant restarts with everything unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
from collections.abc import Callable
from datetime import datetime
from threading import Event, Thread
from typing import Any
from urllib.request import Request, urlopen

from ohana_agent.tsunade.local_time import paris_now
from ohana_agent.tsunade.preventive_rules import HA_NODE, HA_UNAVAILABLE_METRIC

LOGGER = logging.getLogger(__name__)
MAX_BYTES = 32 * 1024 * 1024
MAX_ENTITIES_KEPT = 500


def unavailable_entities(states: Any) -> list[str]:
    if not isinstance(states, list):
        raise ValueError("Home Assistant /api/states must return a list")
    return sorted(
        str(item["entity_id"])
        for item in states
        if isinstance(item, dict)
        and item.get("state") == "unavailable"
        and isinstance(item.get("entity_id"), str)
    )


class HomeAssistantAvailabilitySampler:
    """Background hourly sampler; a failed read is only retried next hour."""

    def __init__(
        self,
        *,
        url: str,
        token: Callable[[], str | None],
        record_metric: Callable[[str, str, float, datetime], None],
        record_snapshot: Callable[[str, str, datetime, dict[str, Any]], None],
        verify_tls: bool = True,
        timeout: float = 20.0,
        interval_seconds: float = 3600.0,
        first_delay_seconds: float = 300.0,
        node: str = HA_NODE,
        fetch: Callable[[], Any] | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.record_metric = record_metric
        self.record_snapshot = record_snapshot
        self.verify_tls = verify_tls
        self.timeout = timeout
        self.interval_seconds = interval_seconds
        self.first_delay_seconds = first_delay_seconds
        self.node = node
        self._fetch = fetch or self._http_states
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(
            target=self._run, name="ohana-ha-availability", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def sample(self) -> int | None:
        try:
            entities = unavailable_entities(self._fetch())
        except Exception as error:  # noqa: BLE001 - one missed hour is harmless.
            LOGGER.info("Home Assistant availability sample skipped: %s", error)
            return None
        now = paris_now()
        self.record_metric(self.node, HA_UNAVAILABLE_METRIC, float(len(entities)), now)
        self.record_snapshot(
            self.node,
            "ha_unavailable_snapshot",
            now,
            {"count": len(entities), "entities": entities[:MAX_ENTITIES_KEPT]},
        )
        return len(entities)

    def _http_states(self) -> Any:
        token = self.token()
        if not token:
            raise ValueError("no Home Assistant access token")
        request = Request(  # noqa: S310 - configured Home Assistant URL.
            f"{self.url}/api/states",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        context = None
        if self.url.startswith("https://") and not self.verify_tls:
            context = ssl._create_unverified_context()  # noqa: SLF001
        with urlopen(request, timeout=self.timeout, context=context) as response:  # noqa: S310
            body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("Home Assistant states exceed the read limit")
        return json.loads(body)

    def _run(self) -> None:
        if self._stop.wait(self.first_delay_seconds):
            return
        while True:
            self.sample()
            if self._stop.wait(self.interval_seconds):
                return


def telemetry_token(config: Any) -> Callable[[], str | None]:
    """The Home Assistant token the telemetry plugin already uses."""

    def resolve() -> str | None:
        if getattr(config, "access_token", None):
            return str(config.access_token)
        variable = getattr(config, "access_token_environment_variable", None)
        return os.getenv(variable) if variable else None

    return resolve
