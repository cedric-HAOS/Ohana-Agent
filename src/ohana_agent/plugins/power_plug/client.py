"""Home Assistant REST client for one switch and its optional power sensor."""

from __future__ import annotations

import json
import ssl
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ohana_agent.jobs.power_plug import PlugReading, PowerPlugError


class HomeAssistantPlug:
    """A switch, and optionally its power sensor, driven through Home Assistant."""

    def __init__(
        self,
        *,
        url: str,
        token: str,
        switch_entity_id: str,
        power_entity_id: str | None = None,
        verify_tls: bool = True,
        timeout_seconds: float = 5.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._switch = switch_entity_id
        self._power = power_entity_id
        self._timeout = timeout_seconds
        self._opener = opener
        self._context = (
            ssl._create_unverified_context()  # noqa: S323, SLF001 - explicit opt-out
            if self._url.startswith("https://") and not verify_tls
            else None
        )

    def read(self) -> PlugReading:
        """State of the switch and, when configured, the load it measures."""
        state = self._state(self._switch)
        if state not in {"on", "off"}:
            raise PowerPlugError(f"the switch is {state}")
        watts: float | None = None
        if self._power is not None:
            try:
                watts = float(self._state(self._power))
            except (PowerPlugError, ValueError):
                watts = None  # an unreadable sensor never counts as "idle"
        return PlugReading(is_on=state == "on", power_watts=watts)

    def turn_on(self) -> None:
        self._call("turn_on")

    def turn_off(self) -> None:
        self._call("turn_off")

    def _state(self, entity_id: str) -> str:
        body = self._request("GET", f"/api/states/{quote(entity_id, safe='._')}")
        state = body.get("state") if isinstance(body, dict) else None
        if not isinstance(state, str):
            raise PowerPlugError("Home Assistant returned an invalid state")
        return state

    def _call(self, service: str) -> None:
        self._request(
            "POST",
            f"/api/services/switch/{service}",
            {"entity_id": self._switch},
        )

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(  # noqa: S310 - scheme checked by the configuration
            f"{self._url}{path}", data=data, headers=headers, method=method
        )
        try:
            with self._opener(
                request, timeout=self._timeout, context=self._context
            ) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except HTTPError as error:
            raise PowerPlugError(f"Home Assistant answered HTTP {error.code}") from None
        except (URLError, OSError, TimeoutError) as error:
            reason = getattr(error, "reason", error)
            raise PowerPlugError(f"Home Assistant unreachable ({reason})") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PowerPlugError("Home Assistant returned invalid JSON") from None
