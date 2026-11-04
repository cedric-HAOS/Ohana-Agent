"""On-demand memory diagnostics of the Agent process.

The preventive rule says the Agent grows; this says where. Nothing runs until
the owner asks: the object census walks the garbage collector's objects once,
and the allocation trace (``tracemalloc``) only exists between an explicit start
and stop, because it costs memory and time on a Raspberry Pi. Reading is the
only effect: nothing here changes what the Agent does.
"""

from __future__ import annotations

import gc
import threading
import tracemalloc
from collections import Counter
from typing import Any

TRACE_FRAMES = 12
DEFAULT_LIMIT = 25
MAX_LIMIT = 100


def _limit(value: int) -> int:
    return max(1, min(int(value), MAX_LIMIT))


def _site(frame: tracemalloc.Frame) -> str:
    return f"{frame.filename}:{frame.lineno}"


def object_census(limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Count live objects by type: a leak shows as a type that keeps growing."""
    limit = _limit(limit)
    gc.collect()
    counts: Counter[str] = Counter()
    objects = gc.get_objects()
    for item in objects:
        kind = type(item)
        counts[f"{kind.__module__}.{kind.__qualname__}"] += 1
    total = len(objects)
    del objects
    return {
        "total_objects": total,
        "types": [
            {"type": name, "count": count} for name, count in counts.most_common(limit)
        ],
    }


class AllocationTrace:
    """Start, read and stop one ``tracemalloc`` comparison against a baseline."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._baseline: tracemalloc.Snapshot | None = None
        self._owned = False

    def running(self) -> bool:
        return self._baseline is not None

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._baseline is None:
                self._owned = not tracemalloc.is_tracing()
                if self._owned:
                    tracemalloc.start(TRACE_FRAMES)
                self._baseline = tracemalloc.take_snapshot()
            return self._state()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._baseline is not None and self._owned:
                tracemalloc.stop()
            self._baseline = None
            self._owned = False
            return self._state()

    def report(self, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        """Allocation sites that grew since the trace started, largest first."""
        limit = _limit(limit)
        with self._lock:
            state = self._state()
            if self._baseline is None:
                return state
            current = tracemalloc.take_snapshot()
            growth = current.compare_to(self._baseline, "lineno")
            traced, peak = tracemalloc.get_traced_memory()
        return {
            **state,
            "traced_bytes": traced,
            "peak_bytes": peak,
            "growth": [
                {
                    "site": _site(entry.traceback[0]),
                    "size_diff_bytes": entry.size_diff,
                    "size_bytes": entry.size,
                    "count_diff": entry.count_diff,
                }
                for entry in growth[:limit]
                if entry.size_diff > 0
            ],
        }

    def _state(self) -> dict[str, Any]:
        return {"tracing": self._baseline is not None, "frames": TRACE_FRAMES}


def memory_report(trace: AllocationTrace, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """The census, plus the allocation growth when a trace is running."""
    report = {"schema_version": 1, "census": object_census(limit)}
    report["trace"] = trace.report(limit)
    return report
