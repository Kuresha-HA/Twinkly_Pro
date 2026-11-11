"""Real-time UDP frame streaming engine for Twinkly (Port 7777, v3 protocol)."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Any

from .client import TwinklyClient, TwinklyError
from .movie_encoder import _normalize_coordinates, generate_effect_frame

_LOGGER = logging.getLogger(__name__)

UDP_RT_PORT = 7777
MAX_FRAGMENT_PAYLOAD = 900  # 300 RGB LEDs or 225 RGBW LEDs per UDP packet


class TwinklyRealtimeStreamer:
    """Manages UDP real-time frame transmission and background procedural streaming."""

    def __init__(self, client: TwinklyClient, port: int = UDP_RT_PORT) -> None:
        """Initialize the UDP streamer for a TwinklyClient."""
        self.client = client
        self.port = port
        self._sock: socket.socket | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self.active_preset: str = ""
        self.active_params: dict[str, Any] = {}

    @property
    def is_streaming(self) -> bool:
        """Return True if a background RT effect loop is currently active."""
        return self._running and self._task is not None and not self._task.done()

    def _ensure_socket(self) -> socket.socket:
        """Create non-blocking UDP socket if not already open."""
        if self._sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            self._sock = sock
        return self._sock

    @staticmethod
    def build_v3_packets(raw_token: bytes, frame_bytes: bytes) -> list[bytes]:
        """Build Twinkly v3 UDP packets from a raw frame buffer.

        Packet header structure (12 bytes):
        - Byte 0: 0x03 (protocol version 3)
        - Bytes 1..8: 8-byte decoded authentication token
        - Bytes 9..10: 0x00, 0x00
        - Byte 11: fragment index (0, 1, 2, ...)
        - Bytes 12..N: LED byte slice (up to 900 bytes per packet)
        """
        token_8 = (raw_token or b"\x00" * 8)[:8].ljust(8, b"\x00")
        packets: list[bytes] = []
        total_len = len(frame_bytes)
        fragment_idx = 0

        for offset in range(0, max(1, total_len), MAX_FRAGMENT_PAYLOAD):
            chunk = frame_bytes[offset : offset + MAX_FRAGMENT_PAYLOAD]
            header = b"\x03" + token_8 + b"\x00\x00" + bytes((fragment_idx & 0xFF,))
            packets.append(header + chunk)
            fragment_idx += 1

        return packets

    async def send_frame(self, frame_bytes: bytes) -> None:
        """Send a single raw RGB/RGBW frame over UDP to the Twinkly device."""
        if not self.client.raw_token:
            await self.client.authenticate()

        raw_token = self.client.raw_token or b"\x00" * 8
        packets = self.build_v3_packets(raw_token, frame_bytes)
        sock = self._ensure_socket()
        target = (self.client.host, self.port)

        for pkt in packets:
            try:
                sock.sendto(pkt, target)
            except OSError as err:
                _LOGGER.debug("UDP sendto error on %s: %s", self.client.host, err)

    async def start_effect_stream(
        self,
        preset: str = "rainbow_wave",
        fps: int = 25,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Switch device to RT mode and start continuous UDP procedural streaming."""
        await self.stop()

        if not self.client.raw_token:
            await self.client.authenticate()

        await self.client.set_mode("rt")
        gestalt = await self.client.get_gestalt()
        layout = await self.client.get_layout()
        norm_coords = _normalize_coordinates(layout.coordinates)

        self.active_preset = preset
        self.active_params = dict(params or {})
        self._running = True
        self._task = asyncio.create_task(
            self._stream_loop(
                preset=preset,
                norm_coords=norm_coords,
                bytes_per_led=gestalt.bytes_per_led,
                fps=max(5, min(60, fps)),
                params=self.active_params,
            )
        )

    async def _stream_loop(
        self,
        preset: str,
        norm_coords: list[tuple[float, float, float]],
        bytes_per_led: int,
        fps: int,
        params: dict[str, Any],
    ) -> None:
        """Background loop sending UDP frames at the target frame rate."""
        frame_interval = 1.0 / float(fps)
        start_time = time.monotonic()
        last_mode_keepalive = start_time

        try:
            while self._running:
                now = time.monotonic()
                elapsed = now - start_time
                # One cycle every 5 seconds at speed=1.0
                phase = elapsed / 5.0

                # Periodically refresh token/RT mode every 45 seconds so device stays in RT
                if now - last_mode_keepalive > 45.0:
                    last_mode_keepalive = now
                    try:
                        await self.client.set_mode("rt")
                    except TwinklyError:
                        pass

                frame = generate_effect_frame(
                    preset=preset,
                    normalized_coords=norm_coords,
                    phase=phase,
                    bytes_per_led=bytes_per_led,
                    params=params,
                )
                await self.send_frame(frame)

                work_duration = time.monotonic() - now
                await asyncio.sleep(max(0.005, frame_interval - work_duration))
        except asyncio.CancelledError:
            pass
        except Exception as err:
            _LOGGER.warning("RT stream loop error on %s: %s", self.client.host, err)
        finally:
            self._running = False

    async def stop(self, restore_mode: str | None = None) -> None:
        """Stop the background UDP streaming loop."""
        self._running = False
        self.active_preset = ""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

        if restore_mode:
            try:
                await self.client.set_mode(restore_mode)
            except TwinklyError:
                pass
