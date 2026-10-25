"""Resident memory of the running process, read from the kernel."""

from __future__ import annotations

from pathlib import Path

STATUS = Path("/proc/self/status")


def process_rss_bytes(status: Path = STATUS) -> int | None:
    """``VmRSS`` of this process in bytes; ``None`` where the file does not exist."""
    try:
        for line in status.read_text(encoding="ascii", errors="replace").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None
