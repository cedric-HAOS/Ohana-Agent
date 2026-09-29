"""Phase 4 hardening: an explainable drift test shared by the newer rules.

Each recent day is compared with what is normal for it:

- adaptive window: the baseline is every measured day before the recent
  week, from 7 up to 28 days, and the threshold follows the metric's own
  day-to-day spread (median absolute deviation), not a fixed number;
- weekly seasonality: with three weeks of baseline covering each weekday
  twice, a day is compared with the same weekday (a busy Sunday is not a
  drift if Sundays are always busy);
- persistence: at least 4 of the 7 recent days above the threshold.

No statistics beyond medians: the result says which days, which threshold
and why, so the user can check it.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Any

RECENT_DAYS = 7
MIN_RECENT_DAYS = 4
MIN_BASELINE_DAYS = 7
MAX_BASELINE_DAYS = 28
SEASONAL_BASELINE_DAYS = 21
PERSISTENCE_DAYS = 4
# 1.4826 * MAD estimates a standard deviation; three of them is unusual.
SPREAD_FACTOR = 3 * 1.4826


def baseline_drift(
    points: list[tuple[date, float]],
    *,
    today: date,
    absolute_floor: float,
    relative_floor: float,
) -> dict[str, Any]:
    """Compare the recent week with its adaptive, possibly weekly, baseline."""
    ordered = sorted(points)
    recent_start = today - timedelta(days=RECENT_DAYS - 1)
    baseline_start = recent_start - timedelta(days=MAX_BASELINE_DAYS)
    recent = [(day, value) for day, value in ordered if recent_start <= day <= today]
    baseline = [
        (day, value) for day, value in ordered if baseline_start <= day < recent_start
    ]
    result: dict[str, Any] = {
        "recent_days": len(recent),
        "baseline_days": len(baseline),
        "seasonal": False,
    }
    if len(recent) < MIN_RECENT_DAYS or len(baseline) < MIN_BASELINE_DAYS:
        return {**result, "state": "insufficient_data"}

    by_weekday: dict[int, list[float]] = {}
    for day, value in baseline:
        by_weekday.setdefault(day.weekday(), []).append(value)
    seasonal = len(baseline) >= SEASONAL_BASELINE_DAYS and all(
        len(by_weekday.get(weekday, [])) >= 2 for weekday in range(7)
    )
    overall = median(value for _, value in baseline)

    def expected(day: date) -> float:
        return median(by_weekday[day.weekday()]) if seasonal else overall

    spread = median(abs(value - expected(day)) for day, value in baseline)
    threshold = max(
        SPREAD_FACTOR * spread,
        absolute_floor,
        relative_floor * abs(overall),
    )
    above = [
        {"day": day.isoformat(), "value": value, "expected": expected(day)}
        for day, value in recent
        if value - expected(day) > threshold
    ]
    recent_median = median(value for _, value in recent)
    return {
        **result,
        "seasonal": seasonal,
        "state": "watch" if len(above) >= PERSISTENCE_DAYS else "ok",
        "baseline_median": round(overall, 2),
        "recent_median": round(recent_median, 2),
        "threshold": round(threshold, 2),
        "days_above": len(above),
        "above": above,
    }
