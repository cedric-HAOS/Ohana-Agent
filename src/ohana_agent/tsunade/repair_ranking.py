"""Reliability and ranking of known repairs, from their verified outcomes.

A known repair carries counters (attempts, successes, failures). A rate alone
misleads: 1 success out of 1 is not better than 19 out of 20. The ranking uses
the lower bound of the Wilson interval (95 %), which is what the counters
justify claiming, and never counts an execution Shikamaru could not verify.
"""

from __future__ import annotations

from datetime import datetime
from math import sqrt
from typing import Any

_Z = 1.96
# Fewer verified outcomes than this cannot support a judgement.
MIN_VERIFIED_OUTCOMES = 3

RELIABILITY_LABELS = {
    "unproven": "Jamais éprouvée : aucune issue vérifiée",
    "to_confirm": "À confirmer : moins de trois issues vérifiées",
    "reliable": "Fiable : réussite constante, dernière issue favorable",
    "mixed": "Mitigée : réussites et échecs",
    "unstable": "Instable : la dernière exécution a échoué",
    "unreliable": "Peu fiable : elle échoue plus souvent qu'elle ne réussit",
}


def wilson_lower_bound(successes: int, decided: int) -> float:
    """Lowest success rate the verified outcomes support at 95 % confidence."""
    if decided <= 0:
        return 0.0
    proportion = successes / decided
    z2 = _Z * _Z
    centre = proportion + z2 / (2 * decided)
    margin = _Z * sqrt((proportion * (1 - proportion) + z2 / (4 * decided)) / decided)
    return max(0.0, (centre - margin) / (1 + z2 / decided))


def _instant(value: Any) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return 0.0


def reliability(
    success_count: int,
    failure_count: int,
    last_success_at: Any = None,
    last_failure_at: Any = None,
) -> str:
    """Classify a known repair; the key is stable, the label is for people."""
    decided = success_count + failure_count
    if decided == 0:
        return "unproven"
    if decided < MIN_VERIFIED_OUTCOMES:
        return "to_confirm"
    rate = success_count / decided
    last_failed = _instant(last_failure_at) > _instant(last_success_at)
    if rate < 0.5:
        return "unreliable"
    if last_failed:
        return "unstable"
    return "reliable" if rate >= 0.8 else "mixed"


def rank_key(
    state: str,
    success_count: int,
    failure_count: int,
    last_success_at: Any = None,
    last_used_at: Any = None,
) -> tuple[Any, ...]:
    """Sort key, best first: active, then reliable, then recently successful."""
    return (
        state != "active",
        -wilson_lower_bound(success_count, success_count + failure_count),
        -_instant(last_success_at),
        -_instant(last_used_at),
    )


def rank_rows(rows: list[Any]) -> list[Any]:
    """Order experience rows (sqlite rows or dicts) from the best repair down."""
    return sorted(
        rows,
        key=lambda row: rank_key(
            row["state"],
            row["success_count"],
            row["failure_count"],
            row["last_success_at"],
            row["last_used_at"],
        ),
    )


def ranking_details(row: Any, position: int) -> dict[str, Any]:
    """Rank, score and reliability of one experience row."""
    decided = int(row["success_count"]) + int(row["failure_count"])
    kind = reliability(
        int(row["success_count"]),
        int(row["failure_count"]),
        row["last_success_at"],
        row["last_failure_at"],
    )
    return {
        "rank": position,
        "score": round(wilson_lower_bound(int(row["success_count"]), decided), 3),
        "success_rate": (
            round(int(row["success_count"]) / decided * 100, 1) if decided else None
        ),
        "reliability": kind,
        "reliability_label": RELIABILITY_LABELS[kind],
    }
