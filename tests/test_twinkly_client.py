"""Unit tests for the Twinkly Pro XLED client, models, movie encoder, and UDP RT packer."""

from __future__ import annotations

import base64
from typing import Any

from aiohttp import web
import pytest

from custom_components.twinkly_pro.twinkly_client import (
    CURATED_GALLERY_TEMPLATES,
    DeviceLayout,
    GestaltInfo,
    MoviesState,
    PlaylistState,
    SyncInfo,
    TwinklyClient,
    TwinklyRealtimeStreamer,
    compile_custom_frames_movie,
    compile_procedural_movie,
)


def test_gestalt_parsing() -> None:
    """Verify GestaltInfo parses device hardware profile accurately."""
    raw = {
        "product_name": "Twinkly",
        "hardware_version": "100",
        "bytes_per_led": 3,
        "hw_id": "001122",
        "product_code": "TWS250STP-B",
        "device_name": "Christmas Tree",
        "mac": "AA:BB:CC:DD:EE:FF",
        "uuid": "12345678-1234-5678-1234-567812345678",
        "number_of_led": 250,
        "led_profile": "RGB",
        "frame_rate": 25.0,
        "movie_capacity": 1200,
    }
    info = GestaltInfo.from_dict(raw)
    assert info.device_name == "Christmas Tree"
    assert info.mac == "aa:bb:cc:dd:ee:ff"
    assert info.number_of_led == 250
    assert info.led_profile == "RGB"
    assert info.bytes_per_led == 3


def test_sync_parsing() -> None:
    """Verify SyncInfo detects master and slave roles properly."""
    master_sync = SyncInfo.from_dict(
        {"sync": {"mode": "master", "group_uid": "grp_123"}}
    )
    assert master_sync.is_grouped is True
    assert master_sync.is_master is True
    assert master_sync.is_slave is False
    assert master_sync.group_uid == "grp_123"

    slave_sync = SyncInfo.from_dict(
        {
            "sync": {
                "mode": "slave",
                "group_uid": "grp_123",
                "master_uid": "uuid_master",
                "slave_id": 1,
            }
        }
    )
    assert slave_sync.is_grouped is True
    assert slave_sync.is_master is False
    assert slave_sync.is_slave is True


def test_movies_and_playlist_linking() -> None:
    """Verify MoviesState and PlaylistState link movie names via unique_id."""
    movies_raw = {
        "movies": [
            {
                "id": 0,
                "name": "Aurora Glow",
                "unique_id": "uid-aurora-1",
                "descriptor_type": "rgb_raw",
                "leds_per_frame": 250,
                "frames_number": 100,
                "fps": 20,
            },
            {
                "id": 1,
                "name": "Cyber Wave",
                "unique_id": "uid-cyber-2",
                "descriptor_type": "rgb_raw",
                "leds_per_frame": 250,
                "frames_number": 120,
                "fps": 25,
            },
        ],
        "available_frames": 980,
        "max_capacity": 1200,
        "max": 15,
    }
    movies_state = MoviesState.from_dict(
        movies_raw, {"id": 1, "unique_id": "uid-cyber-2"}
    )
    assert len(movies_state.movies) == 2
    assert movies_state.current_movie_id == 1

    playlist_raw = {
        "entries": [
            {"unique_id": "uid-aurora-1", "duration": 45},
            {"unique_id": "uid-cyber-2", "duration": 60},
        ]
    }
    playlist_state = PlaylistState.from_dict(
        playlist_raw,
        {"id": 0, "unique_id": "uid-aurora-1"},
        movies=movies_state.movies,
    )
    assert len(playlist_state.entries) == 2
    assert playlist_state.entries[0].name == "Aurora Glow"
    assert playlist_state.entries[0].movie_id == 0
    assert playlist_state.entries[1].name == "Cyber Wave"
    assert playlist_state.entries[1].duration == 60


@pytest.mark.parametrize(
    "preset",
    [
        "rainbow_wave",
        "gradient_flow",
        "plasma_2d",
        "sparkle_twinkle",
        "fire_flame",
        "equalizer_bars",
        "matrix_rain",
        "aurora_borealis",
    ],
)
def test_all_procedural_presets_compile(preset: str) -> None:
    """Verify every built-in procedural 2D/3D preset compiles valid frame buffers."""
    coords = DeviceLayout.create_default_tree_coordinates(40)
    raw_bytes, frames_count, uid = compile_procedural_movie(
        preset=preset,
        coordinates=coords,
        duration_seconds=1.0,
        fps=10,
        bytes_per_led=3,
    )
    assert frames_count == 10
    assert len(raw_bytes) == 10 * 40 * 3
    assert len(uid) == 36


def test_custom_frames_compiler() -> None:
    """Verify custom RGB frames compiler outputs expected binary payload."""
    frames = [
        [[255, 0, 128], [0, 255, 64]],
        [[10, 20, 30], [40, 50, 60]],
    ]
    buf, count = compile_custom_frames_movie(frames, bytes_per_led=3)
    assert count == 2
    assert buf == bytes([255, 0, 128, 0, 255, 64, 10, 20, 30, 40, 50, 60])


def test_udp_v3_packet_fragmentation() -> None:
    """Verify UDP v3 packet builder fragments frames larger than 300 RGB LEDs."""
    token = base64.b64decode("AAECAwQFBgc=")  # 8 bytes
    # 400 RGB LEDs = 1200 bytes -> should split into 2 fragments (900 + 300)
    frame = bytes([i % 256 for i in range(1200)])
    packets = TwinklyRealtimeStreamer.build_v3_packets(token, frame)
    assert len(packets) == 2
    assert packets[0][0] == 3
    assert packets[0][1:9] == token
    assert packets[0][11] == 0
    assert len(packets[0]) == 12 + 900

    assert packets[1][0] == 3
    assert packets[1][11] == 1
    assert len(packets[1]) == 12 + 300


def test_curated_gallery_templates() -> None:
    """Ensure curated gallery templates have valid presets and color parameters."""
    assert len(CURATED_GALLERY_TEMPLATES) >= 8
    for tpl in CURATED_GALLERY_TEMPLATES:
        assert "id" in tpl
        assert "name" in tpl
        assert "preset" in tpl
        assert "params" in tpl


@pytest.mark.asyncio
async def test_client_auth_and_movie_upload_over_http() -> None:
    """Verify TwinklyClient challenge-response auth and movie upload against a live HTTP test server."""
    received_uploads: list[bytes] = []
    state: dict[str, Any] = {"mode": "off"}

    async def handle_gestalt(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "device_name": "Living Room Tree",
                "mac": "11:22:33:44:55:66",
                "uuid": "uuid-tree-1",
                "number_of_led": 10,
                "led_profile": "RGB",
                "bytes_per_led": 3,
                "code": 1000,
            }
        )

    async def handle_login(request: web.Request) -> web.Response:
        body = await request.json()
        assert "challenge" in body
        return web.json_response(
            {
                "authentication_token": "AAECAwQFBgc=",
                "challenge-response": "resp123",
                "code": 1000,
            }
        )

    async def handle_verify(request: web.Request) -> web.Response:
        assert request.headers.get("X-Auth-Token") == "AAECAwQFBgc="
        return web.json_response({"code": 1000})

    async def handle_movies_new(request: web.Request) -> web.Response:
        assert request.headers.get("X-Auth-Token") == "AAECAwQFBgc="
        meta = await request.json()
        assert meta["name"] == "Test Aurora"
        return web.json_response({"id": 3, "code": 1000})

    async def handle_movies_full(request: web.Request) -> web.Response:
        raw = await request.read()
        received_uploads.append(raw)
        return web.json_response({"code": 1000})

    async def handle_movies_current(request: web.Request) -> web.Response:
        return web.json_response({"code": 1000})

    async def handle_led_mode(request: web.Request) -> web.Response:
        if request.method == "POST":
            body = await request.json()
            state["mode"] = body["mode"]
        return web.json_response({"mode": state["mode"], "code": 1000})

    app = web.Application()
    app.router.add_get("/xled/v1/gestalt", handle_gestalt)
    app.router.add_post("/xled/v1/login", handle_login)
    app.router.add_post("/xled/v1/verify", handle_verify)
    app.router.add_post("/xled/v1/movies/new", handle_movies_new)
    app.router.add_post("/xled/v1/movies/full", handle_movies_full)
    app.router.add_post("/xled/v1/movies/current", handle_movies_current)
    app.router.add_get("/xled/v1/led/mode", handle_led_mode)
    app.router.add_post("/xled/v1/led/mode", handle_led_mode)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    client = TwinklyClient(host="127.0.0.1", port=port)
    try:
        payload = bytes(range(150))  # 10 LEDs * 3 bytes * 5 frames
        movie_id = await client.upload_movie(
            name="Test Aurora",
            raw_frames=payload,
            frames_number=5,
            fps=20,
            activate=True,
        )
        assert movie_id == 3
        assert client.auth_token == "AAECAwQFBgc="
        assert len(received_uploads) == 1
        assert received_uploads[0] == payload
        assert await client.get_mode() == "movie"
    finally:
        await client.close()
        await runner.cleanup()
