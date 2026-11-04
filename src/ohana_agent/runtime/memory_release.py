"""Give memory back to the system after a probe that builds a big object graph.

The Z-Wave JS probe loads the whole controller state (about 8 MB of nested
dictionaries and model objects, full of reference cycles) every minute. The
Agent's live objects stay flat, but without a collection right after the probe
that graph waits for the next full garbage collection and the freed pages stay
inside the allocator, so the resident memory only ever ratchets up (+25 MB a
day measured on INFRA-01 while ``/v1/diagnostics/memory`` showed no growing
objects). A collection and ``malloc_trim`` after the probe return them.
"""

from __future__ import annotations

import ctypes
import gc
import logging

LOGGER = logging.getLogger(__name__)


def release_freed_memory() -> None:
    """Collect cyclic garbage, then hand free heap pages back to the system."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        # Not glibc (Windows, macOS, musl): the collection alone is still useful.
        LOGGER.debug("malloc_trim is unavailable on this platform")
