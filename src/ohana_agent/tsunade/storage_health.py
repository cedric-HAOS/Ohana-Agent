"""Read the health signs a failing SD card gives, from the kernel only.

The SD card of INFRA-01 failed on 2026-10-09; the old one answered a write in
284 ms on average well before it died. ``/sys/block/<device>/stat`` counts the
writes completed and the time they took, so the average write latency between
two readings is free to compute. A root file system remounted read-only is the
other classic sign. Nothing here needs a privilege or touches the card.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SECTOR_BYTES = 512
# Below this many writes between two readings the average means nothing: the
# readings keep adding up until there are enough.
MIN_WRITES = 20


@dataclass(frozen=True, slots=True)
class StorageSample:
    write_latency_ms: float | None = None
    written_bytes: int | None = None
    root_readonly: bool | None = None


class StorageSampler:
    """Turn two readings of the block device counters into latency and volume."""

    def __init__(
        self,
        device: str = "mmcblk0",
        *,
        sys_block: Path = Path("/sys/block"),
        mounts: Path = Path("/proc/mounts"),
    ) -> None:
        self._stat = sys_block / device / "stat"
        self._mounts = mounts
        self._latency_base: tuple[int, int] | None = None
        self._sectors_base: int | None = None

    @property
    def available(self) -> bool:
        return self._stat.is_file()

    def sample(self) -> StorageSample:
        if not self.available:
            return StorageSample()
        try:
            fields = [int(value) for value in self._stat.read_text().split()]
            write_ios, write_sectors, write_ticks = fields[4], fields[6], fields[7]
        except (OSError, ValueError, IndexError):
            return StorageSample()
        latency = self._latency(write_ios, write_ticks)
        written = self._written(write_sectors)
        return StorageSample(latency, written, self._root_readonly())

    def _latency(self, ios: int, ticks: int) -> float | None:
        base = self._latency_base
        if base is None or ios < base[0] or ticks < base[1]:
            # First reading, or the counters restarted with a reboot.
            self._latency_base = (ios, ticks)
            return None
        if ios - base[0] < MIN_WRITES:
            return None
        self._latency_base = (ios, ticks)
        return (ticks - base[1]) / (ios - base[0])

    def _written(self, sectors: int) -> int | None:
        base = self._sectors_base
        self._sectors_base = sectors
        if base is None or sectors < base:
            return None
        return (sectors - base) * SECTOR_BYTES

    def _root_readonly(self) -> bool | None:
        try:
            lines = self._mounts.read_text().splitlines()
        except OSError:
            return None
        options: list[str] | None = None
        for line in lines:
            parts = line.split()
            if len(parts) >= 4 and parts[1] == "/":
                options = parts[3].split(",")
        return None if options is None else "ro" in options
