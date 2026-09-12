"""Restricted Wake-on-LAN sender for the configured Katsuyu host."""

from __future__ import annotations

import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WakeOnLanSender:
    """Send a bounded magic-packet burst; never executes a shell command."""

    mac_address: str
    broadcast_address: str = "255.255.255.255"
    port: int = 9
    burst_count: int = 3
    burst_interval_seconds: float = 0.1
    sleeper: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        normalized = re.sub(r"[:-]", "", self.mac_address).lower()
        if not re.fullmatch(r"[0-9a-f]{12}", normalized):
            raise ValueError("Wake-on-LAN MAC address is invalid")
        if self.port < 1 or self.port > 65535:
            raise ValueError("Wake-on-LAN port is invalid")
        if self.burst_count < 1 or self.burst_count > 10:
            raise ValueError("Wake-on-LAN burst count is invalid")
        if self.burst_interval_seconds < 0 or self.burst_interval_seconds > 5:
            raise ValueError("Wake-on-LAN burst interval is invalid")
        object.__setattr__(self, "mac_address", normalized)

    def send(self) -> None:
        """Broadcast the configured magic-packet burst."""
        hardware = bytes.fromhex(self.mac_address)
        packet = b"\xff" * 6 + hardware * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as transport:
            transport.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for index in range(self.burst_count):
                transport.sendto(packet, (self.broadcast_address, self.port))
                if index < self.burst_count - 1 and self.burst_interval_seconds > 0:
                    self.sleeper(self.burst_interval_seconds)
