"""Latest state of every checked capability, for the "what is fine" overview."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ohana_agent.tsunade.local_time import paris_now


class TsunadeCapabilityOverview:
    """Read the latest observation per node/service/capability."""

    def capability_states(
        self, *, max_age: timedelta = timedelta(hours=48)
    ) -> list[dict[str, Any]]:
        """Return states observed within ``max_age``, oldest information dropped.

        A state older than the window is not evidence of anything: the check
        may have been removed or stopped, so it is never shown as fine.
        """
        oldest = paris_now() - max_age
        with self._lock:
            rows = self._connection.execute(
                """SELECT node_id,service_id,capability_id,status,observed_at,
                latency_ms FROM tsunade_capability_state
                ORDER BY node_id,service_id,capability_id"""
            ).fetchall()
        return [
            {
                "node": row["node_id"],
                "service": row["service_id"],
                "capability": row["capability_id"],
                "status": row["status"],
                "observed_at": datetime.fromisoformat(row["observed_at"]),
                "latency_ms": row["latency_ms"],
            }
            for row in rows
            if datetime.fromisoformat(row["observed_at"]) >= oldest
        ]
