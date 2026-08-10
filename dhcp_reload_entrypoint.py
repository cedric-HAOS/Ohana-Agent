"""Dependency-free entry point for the restricted DHCP reload helper.

The helper can be triggered by systemd while the Agent virtual environment is
being replaced.  Loading the implementation by file path avoids importing the
eager ``administration`` package, whose API models require Pydantic.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType


def _load_implementation() -> ModuleType:
    implementation_path = (
        Path(__file__).resolve().parent / "administration" / "dhcp_reload_helper.py"
    )
    specification = importlib.util.spec_from_file_location(
        "_ohana_agent_dhcp_reload_helper",
        implementation_path,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Unable to load DHCP reload helper: {implementation_path}")

    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


_IMPLEMENTATION = _load_implementation()
main: Callable[[], int] = _IMPLEMENTATION.main


if __name__ == "__main__":
    raise SystemExit(main())
