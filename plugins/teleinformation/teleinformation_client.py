"""Small Home Assistant REST client used by Téléinformation checks."""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class HomeAssistantEntityState:
    """Relevant state data returned by Home Assistant."""

    entity_id: str
    state: str | None
    reported_at: str | None
    unit: str | None = None
    error: str | None = None


class HomeAssistantTeleinformationClient:
    """Read one entity state through the Home Assistant REST API."""

    def query_entity(
        self,
        base_url: str,
        entity_id: str,
        *,
        access_token: str,
        timeout: float = 5.0,
        verify_tls: bool = True,
    ) -> HomeAssistantEntityState:
        """Return the current value and latest report timestamp."""
        url = f"{base_url.rstrip('/')}/api/states/{quote(entity_id, safe='.')}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "Ohana-Agent teleinformation check",
            },
        )
        context = None

        if url.lower().startswith("https://") and not verify_tls:
            context = ssl._create_unverified_context()

        try:
            with urlopen(request, timeout=timeout, context=context) as response:
                payload = json.loads(response.read(1_048_576).decode("utf-8"))
        except HTTPError as error:
            body = error.read(4096).decode("utf-8", errors="replace").strip()
            return HomeAssistantEntityState(
                entity_id=entity_id,
                state=None,
                reported_at=None,
                error=(
                    f"Home Assistant returned HTTP {error.code}"
                    + (f": {body}" if body else ".")
                ),
            )
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            return HomeAssistantEntityState(
                entity_id=entity_id,
                state=None,
                reported_at=None,
                error=str(error),
            )

        if not isinstance(payload, dict):
            return HomeAssistantEntityState(
                entity_id=entity_id,
                state=None,
                reported_at=None,
                error="Home Assistant returned an invalid state object.",
            )

        attributes = payload.get("attributes")
        unit = None

        if isinstance(attributes, dict):
            raw_unit = attributes.get("unit_of_measurement")
            unit = raw_unit if isinstance(raw_unit, str) else None

        raw_state = payload.get("state")
        reported_at = (
            payload.get("last_reported")
            or payload.get("last_updated")
            or payload.get("last_changed")
        )
        return HomeAssistantEntityState(
            entity_id=entity_id,
            state=raw_state if isinstance(raw_state, str) else None,
            reported_at=(reported_at if isinstance(reported_at, str) else None),
            unit=unit,
        )
