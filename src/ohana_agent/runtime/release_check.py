"""Phase 5: which Ohana Platform release is recommended, compared to what runs.

The Installer reads the same catalogue, attached to the latest Platform
release on GitHub. The Agent only reads it, every six hours, to show the
available version in Vision; updating stays a user action (``ohana update``).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from threading import Event, Lock, Thread
from typing import Any
from urllib.request import Request, urlopen

import yaml

from ohana_agent.tsunade.local_time import paris_iso, paris_now

LOGGER = logging.getLogger(__name__)

LATEST_RELEASE_URL = (
    "https://api.github.com/repos/cedric-HAOS/Ohana-Platform/releases/latest"
)
KATSUYU_LATEST_URL = (
    "https://api.github.com/repos/cedric-HAOS/Ohana-Katsuyu/releases/latest"
)
CATALOG_ASSET = "release-catalog.yaml"
MAX_BYTES = 256 * 1024


def _read(url: str, timeout: float) -> bytes:
    request = Request(  # noqa: S310 - fixed https GitHub URLs.
        url,
        headers={"User-Agent": "Ohana-Agent", "Accept": "*/*"},
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError(f"{url} exceeds {MAX_BYTES} bytes")
    return body


def fetch_recommended(
    read: Callable[[str, float], bytes] = _read, timeout: float = 15.0
) -> dict[str, Any]:
    """Return the recommended Platform composition of the latest release."""
    release = json.loads(read(LATEST_RELEASE_URL, timeout))
    assets = release.get("assets", [])
    asset = next((item for item in assets if item.get("name") == CATALOG_ASSET), None)
    if asset is None:
        raise ValueError(f"{CATALOG_ASSET} is missing from {release.get('tag_name')}")
    catalog = yaml.safe_load(read(str(asset["browser_download_url"]), timeout))
    default = str(catalog.get("default_platform_version", ""))
    entries = catalog.get("releases") or []
    entry = next(
        (item for item in entries if str(item.get("platform_version")) == default),
        None,
    ) or next((item for item in entries if item.get("status") == "recommended"), None)
    if entry is None:
        raise ValueError("no recommended release in the catalogue")
    # Katsuyu ships outside the Platform composition, on its own releases.
    katsuyu = json.loads(read(KATSUYU_LATEST_URL, timeout))
    katsuyu_tag = str(katsuyu.get("tag_name") or "")
    return {
        "katsuyu_version": katsuyu_tag.removeprefix("v") or None,
        "platform_version": str(entry["platform_version"]),
        "agent_version": str(entry["agent_version"]),
        "vision_version": str(entry["vision_version"]),
        "shizune_version": (
            str(entry["shizune_version"]) if entry.get("shizune_version") else None
        ),
    }


class ReleaseCheck:
    """Poll the catalogue in the background; never blocks a caller."""

    def __init__(
        self,
        *,
        interval_seconds: float = 6 * 3600,
        first_delay_seconds: float = 120,
        fetch: Callable[[], dict[str, Any]] = fetch_recommended,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.first_delay_seconds = first_delay_seconds
        self._fetch = fetch
        self._lock = Lock()
        self._state: dict[str, Any] = {
            "checked_at": None,
            "recommended": None,
            "error": None,
        }
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="ohana-release-check", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def check_now(self) -> dict[str, Any]:
        try:
            recommended = self._fetch()
            error = None
        except Exception as exc:  # noqa: BLE001 - reported, retried later.
            recommended = None
            error = f"{type(exc).__name__}: {exc}"[:200]
            LOGGER.info("Release catalogue unavailable: %s", error)
        with self._lock:
            if recommended is not None:
                self._state["recommended"] = recommended
            self._state["error"] = error
            self._state["checked_at"] = paris_iso(paris_now())
            return dict(self._state)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _run(self) -> None:
        if self._stop.wait(self.first_delay_seconds):
            return
        while True:
            self.check_now()
            if self._stop.wait(self.interval_seconds):
                return


def compare_versions(installed: str | None, recommended: str | None) -> str:
    """``current``, ``outdated``, ``ahead`` or ``unknown``."""
    if not installed or not recommended:
        return "unknown"
    try:
        mine = tuple(int(part) for part in installed.split("."))
        theirs = tuple(int(part) for part in recommended.split("."))
    except ValueError:
        return "unknown"
    if mine == theirs:
        return "current"
    return "outdated" if mine < theirs else "ahead"
