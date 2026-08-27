"""Tests for the restricted Wake-on-LAN sender."""

from __future__ import annotations

import socket

import pytest

from administration.wake_on_lan import WakeOnLanSender


class FakeSocket:
    def __init__(self) -> None:
        self.options: list[tuple[int, int, int]] = []
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, *args: object) -> None:
        self.closed = True

    def setsockopt(self, level: int, option: int, value: int) -> None:
        self.options.append((level, option, value))

    def sendto(self, packet: bytes, address: tuple[str, int]) -> None:
        self.sent.append((packet, address))


def test_wake_on_lan_sender_broadcasts_a_magic_packet_burst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_socket = FakeSocket()
    sleeps: list[float] = []

    monkeypatch.setattr(
        socket,
        "socket",
        lambda family, kind: fake_socket,
    )

    WakeOnLanSender(
        mac_address="AA:BB:CC:DD:EE:FF",
        broadcast_address="192.168.1.255",
        port=9,
        burst_count=3,
        burst_interval_seconds=0.25,
        sleeper=sleeps.append,
    ).send()

    expected_packet = b"\xff" * 6 + bytes.fromhex("AABBCCDDEEFF") * 16
    assert fake_socket.options == [(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)]
    assert fake_socket.sent == [
        (expected_packet, ("192.168.1.255", 9)),
        (expected_packet, ("192.168.1.255", 9)),
        (expected_packet, ("192.168.1.255", 9)),
    ]
    assert sleeps == [0.25, 0.25]
    assert fake_socket.closed is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"burst_count": 0},
        {"burst_count": 11},
        {"burst_interval_seconds": -0.1},
        {"burst_interval_seconds": 5.1},
    ],
)
def test_wake_on_lan_sender_rejects_unbounded_burst_settings(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        WakeOnLanSender(
            mac_address="AA:BB:CC:DD:EE:FF",
            **overrides,
        )
