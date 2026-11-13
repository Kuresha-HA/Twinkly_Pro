"""Procedural 2D/3D effect generator and Twinkly .movie binary compiler."""

from __future__ import annotations

import colorsys
import hashlib
import math
from typing import Any

from .models import LedCoordinate


def _hsv_to_rgb_bytes(h: float, s: float, v: float, bytes_per_led: int = 3) -> bytes:
    """Convert HSV (0..1) to RGB or RGBW bytes."""
    r_f, g_f, b_f = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    r = max(0, min(255, int(r_f * 255)))
    g = max(0, min(255, int(g_f * 255)))
    b = max(0, min(255, int(b_f * 255)))
    if bytes_per_led == 4:
        # Format for RGBW raw buffer in Twinkly is W, R, G, B or R, G, B, W depending on descriptor;
        # standard rgbw_raw is R, G, B, W
        w = int(min(r, g, b) * (1.0 - s) * 0.5)
        return bytes((r, g, b, w))
    return bytes((r, g, b))


def _lerp_color(
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
    t: float,
    bytes_per_led: int = 3,
) -> bytes:
    """Linearly interpolate between two RGB colors."""
    t_clamped = max(0.0, min(1.0, t))
    r = int(c1[0] + (c2[0] - c1[0]) * t_clamped)
    g = int(c1[1] + (c2[1] - c1[1]) * t_clamped)
    b = int(c1[2] + (c2[2] - c1[2]) * t_clamped)
    if bytes_per_led == 4:
        return bytes((r, g, b, 0))
    return bytes((r, g, b))


def _hex_to_rgb(hex_str: str, default: tuple[int, int, int] = (255, 0, 128)) -> tuple[int, int, int]:
    """Parse #RRGGBB hex string to (R, G, B) tuple."""
    clean = hex_str.strip().lstrip("#")
    if len(clean) == 6:
        try:
            return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))
        except ValueError:
            pass
    return default


def _normalize_coordinates(
    coordinates: list[LedCoordinate],
) -> list[tuple[float, float, float]]:
    """Normalize LED coordinates so x, y, z are all within [0.0, 1.0]."""
    if not coordinates:
        return []
    xs = [c.x for c in coordinates]
    ys = [c.y for c in coordinates]
    zs = [c.z for c in coordinates]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)

    span_x = (max_x - min_x) or 1.0
    span_y = (max_y - min_y) or 1.0
    span_z = (max_z - min_z) or 1.0

    return [
        (
            (c.x - min_x) / span_x,
            (c.y - min_y) / span_y,
            (c.z - min_z) / span_z,
        )
        for c in coordinates
    ]


def _rgb_buffer_to_aww(buf: bytearray) -> bytes:
    """Convert an RGB byte buffer into Amber / Warm White / Cold White (AWW) channels."""
    out = bytearray(len(buf))
    for i in range(0, len(buf) - 2, 3):
        r, g, b = buf[i], buf[i + 1], buf[i + 2]
        amber = min(255, int(r * 0.85 + g * 0.20))
        warm_white = min(255, int((r + g + b) / 3.0))
        cold_white = min(255, int(b * 0.85 + g * 0.20))
        out[i] = amber
        out[i + 1] = warm_white
        out[i + 2] = cold_white
    return bytes(out)


def generate_effect_frame(
    preset: str,
    normalized_coords: list[tuple[float, float, float]],
    phase: float,
    bytes_per_led: int = 3,
    params: dict[str, Any] | None = None,
    color_profile: str = "RGB",
) -> bytes:
    """Generate a single binary frame for the given effect preset and normalized coordinates.

    `phase` progresses continuously (e.g., 0.0 -> 1.0 per cycle).
    """
    cfg = params or {}
    speed = float(cfg.get("speed", 1.0))
    scale = float(cfg.get("scale", 1.0))
    primary_rgb = _hex_to_rgb(str(cfg.get("primary_color", "#ff007f")), (255, 0, 127))
    secondary_rgb = _hex_to_rgb(str(cfg.get("secondary_color", "#00e5ff")), (0, 229, 255))
    tertiary_rgb = _hex_to_rgb(str(cfg.get("tertiary_color", "#7c00ff")), (124, 0, 255))

    t = phase * speed
    buf = bytearray()

    for idx, (nx, ny, nz) in enumerate(normalized_coords):
        if preset == "rainbow_wave":
            hue = (nx * 0.6 * scale + ny * 0.8 * scale + nz * 0.3 - t) % 1.0
            buf.extend(_hsv_to_rgb_bytes(hue, 0.95, 1.0, bytes_per_led))

        elif preset == "gradient_flow":
            wave = 0.5 + 0.5 * math.sin((ny * 3.5 * scale + nx * 1.5 * scale - t) * 2.0 * math.pi)
            if wave < 0.5:
                buf.extend(_lerp_color(primary_rgb, secondary_rgb, wave * 2.0, bytes_per_led))
            else:
                buf.extend(_lerp_color(secondary_rgb, tertiary_rgb, (wave - 0.5) * 2.0, bytes_per_led))

        elif preset == "plasma_2d":
            v1 = math.sin((nx * 4.0 * scale + t) * 2.0 * math.pi)
            v2 = math.sin((ny * 4.0 * scale - t * 0.8) * 2.0 * math.pi)
            v3 = math.sin(((nx + ny + nz) * 2.5 * scale + t * 0.5) * 2.0 * math.pi)
            plasma = (v1 + v2 + v3) / 6.0 + 0.5
            hue = (plasma * 0.75 + t * 0.2) % 1.0
            buf.extend(_hsv_to_rgb_bytes(hue, 0.9, 1.0, bytes_per_led))

        elif preset == "sparkle_twinkle":
            # Deterministic pseudo-random phase offset per LED index
            seed_hash = ((idx * 2654435761) & 0xFFFFFFFF) / 0xFFFFFFFF
            local_wave = math.sin((t * 1.5 + seed_hash) * 2.0 * math.pi)
            sparkle = max(0.0, (local_wave - 0.72) / 0.28)
            base = _lerp_color(primary_rgb, (255, 255, 255), sparkle, bytes_per_led)
            # Dim background slightly so sparkles pop
            factor = 0.22 + 0.78 * sparkle
            if bytes_per_led == 4:
                buf.extend(
                    bytes(
                        (
                            int(base[0] * factor),
                            int(base[1] * factor),
                            int(base[2] * factor),
                            int(255 * (sparkle**2)),
                        )
                    )
                )
            else:
                buf.extend(
                    bytes(
                        (
                            int(base[0] * factor),
                            int(base[1] * factor),
                            int(base[2] * factor),
                        )
                    )
                )

        elif preset == "fire_flame":
            # Bottom (ny=0) is hot white/yellow, top (ny=1) cools to red/ember
            flicker = 0.5 + 0.5 * math.sin(
                (nx * 6.0 + ny * 3.0 - t * 3.0 + (idx % 7) * 0.4) * 2.0 * math.pi
            )
            heat = max(0.0, min(1.0, (1.0 - ny * 0.85) + (flicker - 0.5) * 0.35))
            # Hue from 0.0 (red) to 0.14 (warm yellow)
            hue = heat * 0.12
            sat = 1.0 - max(0.0, (heat - 0.85) * 3.0)
            val = min(1.0, heat * 1.25)
            buf.extend(_hsv_to_rgb_bytes(hue, sat, val, bytes_per_led))

        elif preset == "equalizer_bars":
            # Divide horizontal space into 8 virtual equalizer bands
            band = int(nx * 7.99)
            band_freq = 1.0 + (band % 4) * 0.5
            band_phase = band * 0.37
            bar_height = 0.2 + 0.75 * (
                0.5 + 0.5 * math.sin((t * band_freq + band_phase) * 2.0 * math.pi)
            )
            if ny <= bar_height:
                # Color transitions from green/cyan at bottom to magenta/red at top
                hue = (0.45 - ny * 0.45) % 1.0
                buf.extend(_hsv_to_rgb_bytes(hue, 0.95, 1.0, bytes_per_led))
            elif abs(ny - bar_height) < 0.06:
                # Peak indicator dot
                buf.extend(bytes((255, 255, 255, 0)[:bytes_per_led]))
            else:
                buf.extend(bytes((8, 8, 18, 0)[:bytes_per_led]))

        elif preset == "matrix_rain":
            col = int(nx * 12.0)
            col_offset = ((col * 1597334677) & 0xFFFF) / 0xFFFF
            drop_y = (1.0 - ((t * 1.2 + col_offset) % 1.0))
            dist = (ny - drop_y) % 1.0
            if dist < 0.28:
                intensity = 1.0 - (dist / 0.28)
                head = dist < 0.04
                r = 180 if head else int(primary_rgb[0] * intensity * 0.2)
                g = 255 if head else int(max(180, primary_rgb[1]) * intensity)
                b = 180 if head else int(primary_rgb[2] * intensity * 0.3)
                buf.extend(bytes((r, g, b, 0)[:bytes_per_led]))
            else:
                buf.extend(bytes((0, 12, 4, 0)[:bytes_per_led]))

        elif preset == "aurora_borealis":
            curtain = math.sin((nx * 2.5 * scale + nz * 1.5 + t * 0.7) * 2.0 * math.pi)
            band_center = 0.5 + 0.25 * curtain
            dist = abs(ny - band_center)
            glow = max(0.0, 1.0 - dist * 2.6)
            hue = (0.38 + ny * 0.28 + 0.08 * curtain) % 1.0
            buf.extend(_hsv_to_rgb_bytes(hue, 0.88, glow, bytes_per_led))

        else:
            # Default fallback: rainbow wave
            hue = (ny + t) % 1.0
            buf.extend(_hsv_to_rgb_bytes(hue, 1.0, 1.0, bytes_per_led))

    if color_profile.upper() == "AWW" and bytes_per_led == 3:
        return _rgb_buffer_to_aww(buf)
    return bytes(buf)


def compile_procedural_movie(
    preset: str,
    coordinates: list[LedCoordinate],
    duration_seconds: float = 6.0,
    fps: int = 20,
    bytes_per_led: int = 3,
    params: dict[str, Any] | None = None,
    color_profile: str = "RGB",
) -> tuple[bytes, int, str]:
    """Compile a full multi-frame binary .movie buffer for Twinkly flash memory.

    Returns `(raw_buffer, frames_count, deterministic_unique_id)`.
    """
    frames_count = max(10, min(600, int(duration_seconds * fps)))
    normalized = _normalize_coordinates(coordinates)
    if not normalized:
        normalized = [(0.5, i / 99.0, 0.5) for i in range(100)]

    full_buffer = bytearray()
    for frame_idx in range(frames_count):
        phase = frame_idx / float(frames_count)
        frame_bytes = generate_effect_frame(
            preset=preset,
            normalized_coords=normalized,
            phase=phase,
            bytes_per_led=bytes_per_led,
            params=params,
            color_profile=color_profile,
        )
        full_buffer.extend(frame_bytes)

    raw_bytes = bytes(full_buffer)
    digest = hashlib.sha256(raw_bytes[:4096] + preset.encode("utf-8")).hexdigest()
    # Format as UUID string
    uid = f"{digest[0:8]}-{digest[8:12]}-4{digest[13:16]}-a{digest[17:20]}-{digest[20:32]}"
    return raw_bytes, frames_count, uid


def compile_custom_frames_movie(
    frames_rgb: list[list[list[int]]],
    bytes_per_led: int = 3,
) -> tuple[bytes, int]:
    """Compile a user-created frame array from the Web Panel into a binary .movie buffer.

    `frames_rgb` is a list of frames, where each frame is a list of `[R, G, B]` (or `[R, G, B, W]`) per LED.
    """
    buf = bytearray()
    for frame in frames_rgb:
        for pixel in frame:
            r = max(0, min(255, int(pixel[0]))) if len(pixel) > 0 else 0
            g = max(0, min(255, int(pixel[1]))) if len(pixel) > 1 else 0
            b = max(0, min(255, int(pixel[2]))) if len(pixel) > 2 else 0
            if bytes_per_led == 4:
                w = max(0, min(255, int(pixel[3]))) if len(pixel) > 3 else 0
                buf.extend((r, g, b, w))
            else:
                buf.extend((r, g, b))
    return bytes(buf), len(frames_rgb)
