"""The Agent's own vitals, memory diagnostics and system updates."""

from __future__ import annotations

import logging
import time
from typing import Any

from ohana_agent.runtime.memory_diagnostics import memory_report

LOGGER = logging.getLogger(__name__)


class SystemServiceMixin:
    """The Agent's own vitals, memory diagnostics and system updates."""

    def read_agent_vitals(self) -> object:
        """Phase 5: scheduler, queues, storage, retention and versions."""
        if self.self_report is None:
            raise LookupError("Le détail des vitaux de l'Agent est indisponible")
        return self.self_report()

    def read_memory_diagnostics(self) -> object:
        """Object census and, while a trace runs, the allocation sites that grew."""
        return memory_report(self.allocation_trace)

    def control_memory_trace(self, payload: dict[str, Any]) -> object:
        """Start or stop the allocation trace (costly: only while diagnosing)."""
        action = payload.get("action")
        if action == "start":
            return self.allocation_trace.start()
        if action == "stop":
            return self.allocation_trace.stop()
        raise ValueError("action must be start or stop")

    def read_system_updates(self) -> object:
        """Pending OS package updates; the simulation is kept for two minutes."""
        if self.system_updates_reader is None:
            raise LookupError("L'état des mises à jour système est indisponible")
        helper = (
            self.system_update_requester.status()
            if self.system_update_requester is not None
            else None
        )
        # While apt runs the simulation would read a half-installed system:
        # keep the last answer and let the helper's progress speak.
        running = helper is not None and any(
            helper.get(action, {}).get("state") == "running"
            for action in ("refresh", "upgrade")
        )
        cached = self._system_updates_cache
        if cached is None or (not running and time.monotonic() - cached[0] >= 120):
            cached = (time.monotonic(), self.system_updates_reader())
            self._system_updates_cache = cached
        return cached[1] if helper is None else {**cached[1], "helper": helper}

    def request_system_update(self, action: str) -> object:
        """Ask the Installer helper to refresh the lists or apply the upgrade.

        Nothing is installed without the owner's click in Vision, apt only
        changes packages already installed, and the machine is never restarted.
        """
        if self.system_updates_reader is None or self.system_update_requester is None:
            raise LookupError("La mise à jour système est indisponible")
        if action == "upgrade":
            # The page the owner clicked on shows this same reading: re-running apt
            # here would be slow on the Pi and could outlast Vision's timeout.
            state = self.read_system_updates()
            if state["lists_stale"]:
                raise ValueError(
                    "Les listes de paquets sont périmées : les actualiser avant "
                    "de mettre à jour"
                )
            if not state["pending_count"]:
                raise ValueError("Aucune mise à jour n'est en attente")
        result = self.system_update_requester.request(action)
        # The pending list is stale once apt ran: expire it, keep it for display.
        if self._system_updates_cache is not None:
            self._system_updates_cache = (
                float("-inf"),
                self._system_updates_cache[1],
            )
        return result
