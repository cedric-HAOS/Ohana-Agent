"""Ohana-Vision client contract."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VisionClient(Protocol):
    """Minimal contract required to send data to Ohana-Vision."""

    def send_observation(
        self,
        payload: dict[str, Any],
    ) -> None:
        """Send a serialized observation to Ohana-Vision."""

    def send_infrastructure(
        self,
        payload: dict[str, Any],
    ) -> None:
        """Send an infrastructure snapshot to Ohana-Vision."""
