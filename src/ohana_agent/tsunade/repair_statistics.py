"""Detailed success statistics of supervised repairs (Phase 3 hardening).

Read only, from what the repositories already record: the repairs table, the
incidents it belongs to and the known repairs. Nothing here decides anything;
Vision shows it and Tsunade's proposal only reads the ranking.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from ohana_agent.tsunade.local_time import paris_iso, paris_now
from ohana_agent.tsunade.repair_ranking import (
    rank_rows,
    ranking_details,
    wilson_lower_bound,
)

PERIODS = {"7d": 7, "30d": 30, "all": None}
_STATUSES = (
    "proposed",
    "authorized",
    "refused",
    "expired",
    "verifying",
    "succeeded",
    "failed",
    "unverified",
)


def _seconds(start: Any, end: Any) -> float | None:
    try:
        return (
            datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))
        ).total_seconds()
    except (TypeError, ValueError):
        return None


def _median(values: list[float | None]) -> int | None:
    kept = [value for value in values if value is not None and value >= 0]
    return round(median(kept)) if kept else None


def summarize(rows: list[Any]) -> dict[str, Any]:
    """Counts, rates and typical delays of a set of repair proposals."""
    status = Counter(str(row["status"]) for row in rows)
    executed = [row for row in rows if row["executed_at"]]
    succeeded = status["succeeded"]
    failed = status["failed"]
    decided = succeeded + failed
    authorized = [row for row in rows if row["authorized_at"]]
    return {
        "proposed": len(rows),
        "authorized": len(authorized),
        "refused": status["refused"],
        "expired": status["expired"],
        "pending": status["proposed"],
        "executed": len(executed),
        "succeeded": succeeded,
        "failed": failed,
        # Shikamaru could not tell: neither a success nor a failure.
        "unverified": status["unverified"],
        "verifying": status["verifying"],
        "success_rate": round(succeeded / decided * 100, 1) if decided else None,
        "reliable_rate": (
            round(wilson_lower_bound(succeeded, decided) * 100, 1) if decided else None
        ),
        "median_decision_seconds": _median(
            [_seconds(row["proposed_at"], row["authorized_at"]) for row in authorized]
        ),
        "median_recovery_seconds": _median(
            [
                _seconds(row["executed_at"], row["verified_at"])
                for row in executed
                if row["status"] == "succeeded"
            ]
        ),
    }


def _failure_causes(rows: list[Any]) -> list[dict[str, Any]]:
    causes = Counter(
        str(row["result"] or "cause non renseignée")[:160]
        for row in rows
        if row["status"] == "failed"
    )
    return [{"cause": cause, "count": count} for cause, count in causes.most_common(5)]


class TsunadeRepairStatistics:
    """Read-only repair statistics and known repair ranking."""

    def ranked_experiences(self) -> list[tuple[Any, dict[str, Any]]]:
        """Known repairs best first, each with its rank, score and reliability."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM tsunade_experiences"
            ).fetchall()
        ranked = rank_rows(rows)
        return [
            (self._experience(row), ranking_details(row, position))
            for position, row in enumerate(ranked, start=1)
        ]

    def repair_statistics(self) -> dict[str, Any]:
        now = paris_now()
        with self._lock:
            rows = self._connection.execute(
                """SELECT r.repair_id, r.operation, r.target, r.status,
                r.proposed_at, r.authorized_at, r.executed_at, r.verified_at,
                r.result, r.experience_id, i.equipment_id, i.capability_id
                FROM tsunade_repairs r JOIN tsunade_incidents i
                ON i.incident_id = r.incident_id
                ORDER BY julianday(r.proposed_at)"""
            ).fetchall()
        periods: dict[str, Any] = {}
        for name, days in PERIODS.items():
            cutoff = now - timedelta(days=days) if days else None
            subset = [
                row
                for row in rows
                if cutoff is None
                or (_seconds(cutoff.isoformat(), row["proposed_at"]) or 0) >= 0
            ]
            periods[name] = summarize(subset)

        def grouped(keys: tuple[str, ...]) -> list[dict[str, Any]]:
            groups: dict[tuple[str, ...], list[Any]] = {}
            for row in rows:
                groups.setdefault(tuple(row[key] for key in keys), []).append(row)
            result = []
            for key, members in groups.items():
                executed = [row for row in members if row["executed_at"]]
                last_success = max(
                    (
                        row["verified_at"]
                        for row in members
                        if row["status"] == "succeeded"
                    ),
                    default=None,
                )
                last_failure = max(
                    (
                        row["verified_at"] or row["executed_at"]
                        for row in members
                        if row["status"] == "failed"
                    ),
                    default=None,
                )
                result.append(
                    {
                        **dict(zip(keys, key, strict=True)),
                        **summarize(members),
                        "last_success_at": paris_iso(last_success)
                        if last_success
                        else None,
                        "last_failure_at": paris_iso(last_failure)
                        if last_failure
                        else None,
                        "failure_causes": _failure_causes(members),
                        "executions": len(executed),
                    }
                )
            return sorted(
                result,
                key=lambda item: (-item["executed"], -item["proposed"]),
            )

        return {
            "schema_version": 1,
            "generated_at": now.isoformat(),
            "periods": periods,
            "by_repair": grouped(("operation", "target")),
            "by_equipment": grouped(("equipment_id",)),
            "by_capability": grouped(("equipment_id", "capability_id")),
            "ranking": [
                {
                    "experience_id": str(experience.experience_id),
                    "equipment_id": experience.equipment_id,
                    "capability_id": experience.capability_id,
                    "action": experience.action,
                    "state": experience.state,
                    "attempt_count": experience.attempt_count,
                    "success_count": experience.success_count,
                    "failure_count": experience.failure_count,
                    **details,
                }
                for experience, details in self.ranked_experiences()
            ],
        }
