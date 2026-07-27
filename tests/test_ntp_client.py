"""Tests for the native SNTP client."""

import struct
from collections.abc import Callable

import pytest

from plugins.ntp.ntp_client import NTP_EPOCH_DELTA, NTPClient


def pack_timestamp(timestamp: float) -> bytes:
    ntp_timestamp = timestamp + NTP_EPOCH_DELTA
    seconds = int(ntp_timestamp)
    fraction = int((ntp_timestamp - seconds) * (1 << 32))
    return struct.pack("!II", seconds, fraction)


class FakeSocket:
    def __init__(
        self,
        response_factory: Callable[[bytes], bytes],
    ) -> None:
        self._response_factory = response_factory
        self.sent_packet = b""
        self.timeout: float | None = None
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def sendto(self, packet: bytes, address: tuple[str, int]) -> None:
        self.sent_packet = packet
        self.address = address

    def recvfrom(self, size: int) -> tuple[bytes, tuple[str, int]]:
        del size
        return self._response_factory(self.sent_packet), ("192.168.1.10", 123)

    def close(self) -> None:
        self.closed = True


def make_response(
    request: bytes,
    *,
    receive_time: float,
    transmit_time: float,
    leap_indicator: int = 0,
    stratum: int = 2,
) -> bytes:
    response = bytearray(48)
    response[0] = (leap_indicator << 6) | (4 << 3) | 4
    response[1] = stratum
    response[24:32] = request[40:48]
    response[32:40] = pack_timestamp(receive_time)
    response[40:48] = pack_timestamp(transmit_time)
    return bytes(response)


def test_ntp_client_calculates_offset_and_round_trip() -> None:
    request_time = 1_700_000_000.0
    response_time = request_time + 0.040
    socket_instance = FakeSocket(
        lambda request: make_response(
            request,
            receive_time=request_time + 0.015,
            transmit_time=request_time + 0.025,
        )
    )
    clock_values = iter([request_time, response_time])
    client = NTPClient(
        socket_factory=lambda family, kind: socket_instance,
        wall_clock=lambda: next(clock_values),
    )

    result = client.query("192.168.1.10", timeout=1.5)

    assert result.success is True
    assert result.server == "192.168.1.10"
    assert result.source_address == "192.168.1.10"
    assert result.offset_ms == pytest.approx(0.0, abs=0.001)
    assert result.round_trip_ms == pytest.approx(30.0, abs=0.001)
    assert result.stratum == 2
    assert result.version == 4
    assert result.leap_indicator == 0
    assert socket_instance.timeout == 1.5
    assert socket_instance.address == ("192.168.1.10", 123)
    assert socket_instance.closed is True


def test_ntp_client_rejects_unsynchronized_server() -> None:
    request_time = 1_700_000_000.0
    socket_instance = FakeSocket(
        lambda request: make_response(
            request,
            receive_time=request_time + 0.010,
            transmit_time=request_time + 0.020,
            leap_indicator=3,
        )
    )
    clock_values = iter([request_time, request_time + 0.030])
    client = NTPClient(
        socket_factory=lambda family, kind: socket_instance,
        wall_clock=lambda: next(clock_values),
    )

    result = client.query("192.168.1.10")

    assert result.success is False
    assert result.error == "NTP server reports an unsynchronized clock."


def test_ntp_client_returns_socket_error() -> None:
    class FailingSocket(FakeSocket):
        def sendto(self, packet: bytes, address: tuple[str, int]) -> None:
            del packet, address
            raise TimeoutError("timed out")

    socket_instance = FailingSocket(lambda request: request)
    client = NTPClient(
        socket_factory=lambda family, kind: socket_instance,
        wall_clock=lambda: 1_700_000_000.0,
    )

    result = client.query("192.168.1.10")

    assert result.success is False
    assert result.error == "timed out"
    assert socket_instance.closed is True


def test_ntp_client_rejects_boolean_port() -> None:
    client = NTPClient()

    with pytest.raises(ValueError, match="port"):
        client.query("192.168.1.10", port=True)
