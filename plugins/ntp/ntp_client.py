"""Minimal SNTP client used by the NTP plugin."""

from __future__ import annotations

import socket
import struct
from collections.abc import Callable
from time import time
from typing import Any

from plugins.ntp.ntp_result import NTPResult

NTP_EPOCH_DELTA = 2_208_988_800
NTP_PACKET_SIZE = 48
NTP_CLIENT_HEADER = 0x23


class NTPClient:
    """Query an NTP server through one RFC 4330 compatible SNTP exchange."""

    def __init__(
        self,
        *,
        socket_factory: Callable[[int, int], Any] = socket.socket,
        wall_clock: Callable[[], float] = time,
    ) -> None:
        self._socket_factory = socket_factory
        self._wall_clock = wall_clock

    def query(
        self,
        server: str,
        *,
        port: int = 123,
        timeout: float = 2.0,
    ) -> NTPResult:
        """Send one SNTP request and calculate offset and round-trip delay."""
        normalized_server = server.strip()

        if not normalized_server:
            raise ValueError("server must not be empty.")

        if isinstance(port, bool) or not 1 <= port <= 65_535:
            raise ValueError("port must be between 1 and 65535.")

        if timeout <= 0:
            raise ValueError("timeout must be greater than zero.")

        request_time = self._wall_clock()
        packet = self._build_request(request_time)
        ntp_socket = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            ntp_socket.settimeout(timeout)
            ntp_socket.sendto(packet, (normalized_server, port))
            payload, source = ntp_socket.recvfrom(512)
            response_time = self._wall_clock()
        except OSError as error:
            return NTPResult(
                server=normalized_server,
                port=port,
                success=False,
                error=str(error),
            )
        finally:
            ntp_socket.close()

        source_address = source[0] if source else None

        try:
            return self._parse_response(
                payload,
                request_packet=packet,
                request_time=request_time,
                response_time=response_time,
                server=normalized_server,
                port=port,
                source_address=source_address,
            )
        except ValueError as error:
            return NTPResult(
                server=normalized_server,
                port=port,
                success=False,
                source_address=source_address,
                error=str(error),
            )

    @staticmethod
    def _build_request(timestamp: float) -> bytes:
        packet = bytearray(NTP_PACKET_SIZE)
        packet[0] = NTP_CLIENT_HEADER
        seconds, fraction = NTPClient._pack_timestamp(timestamp)
        struct.pack_into("!II", packet, 40, seconds, fraction)
        return bytes(packet)

    @staticmethod
    def _parse_response(
        payload: bytes,
        *,
        request_packet: bytes,
        request_time: float,
        response_time: float,
        server: str,
        port: int,
        source_address: str | None,
    ) -> NTPResult:
        if len(payload) < NTP_PACKET_SIZE:
            raise ValueError("NTP response is shorter than 48 bytes.")

        flags = payload[0]
        leap_indicator = flags >> 6
        version = (flags >> 3) & 0x07
        mode = flags & 0x07
        stratum = payload[1]

        if mode != 4:
            raise ValueError(f"Unexpected NTP response mode: {mode}.")

        if version not in {3, 4}:
            raise ValueError(f"Unsupported NTP version: {version}.")

        if leap_indicator == 3:
            raise ValueError("NTP server reports an unsynchronized clock.")

        if not 1 <= stratum <= 15:
            raise ValueError(f"Invalid NTP stratum: {stratum}.")

        if payload[24:32] != request_packet[40:48]:
            raise ValueError("NTP response does not match the request timestamp.")

        receive_time = NTPClient._unpack_timestamp(payload, 32)
        transmit_time = NTPClient._unpack_timestamp(payload, 40)

        offset_ms = (
            ((receive_time - request_time) + (transmit_time - response_time))
            / 2
            * 1000
        )
        round_trip_ms = max(
            0.0,
            (
                (response_time - request_time)
                - (transmit_time - receive_time)
            )
            * 1000,
        )

        return NTPResult(
            server=server,
            port=port,
            success=True,
            source_address=source_address,
            offset_ms=offset_ms,
            round_trip_ms=round_trip_ms,
            stratum=stratum,
            version=version,
            leap_indicator=leap_indicator,
        )

    @staticmethod
    def _pack_timestamp(timestamp: float) -> tuple[int, int]:
        ntp_timestamp = timestamp + NTP_EPOCH_DELTA
        seconds = int(ntp_timestamp)
        fraction = int((ntp_timestamp - seconds) * (1 << 32))
        return seconds, fraction

    @staticmethod
    def _unpack_timestamp(payload: bytes, offset: int) -> float:
        seconds, fraction = struct.unpack_from("!II", payload, offset)
        return seconds - NTP_EPOCH_DELTA + fraction / (1 << 32)
