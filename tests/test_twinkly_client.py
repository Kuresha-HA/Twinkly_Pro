"""Unit tests for the Twinkly Pro XLED client, models, movie encoder, and UDP RT packer."""

from __future__ import annotations

import base64
from typing import Any

from aiohttp import web
import pytest

from custom_components.twinkly_pro.twinkly_client import (
    CURATED_GALLERY_TEMPLATES,
    DeviceCapabilities,
    DeviceLayout,
    DiscoveredTwinklyDevice,
    GestaltInfo,
    MoviesState,
    PlaylistState,
    SyncInfo,
    TwinklyClient,
    TwinklyCloudClient,
    TwinklyRealtimeStreamer,
    compile_custom_frames_movie,
    compile_procedural_movie,
)
from custom_components.twinkly_pro.twinkly_client.discovery import (
    _TwinklyDiscoveryProtocol,
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


def test_udp_5555_discovery_packet_parsing() -> None:
    """Verify UDP port 5555 discovery response packet parses device name and IP."""
    proto = _TwinklyDiscoveryProtocol()
    # 4 reversed IP bytes + b'OK' + b'Curtain-400\x00'
    packet = bytes([145, 1, 168, 192]) + b"OKCurtain-400\x00"
    proto.datagram_received(packet, ("192.168.1.145", 5555))
    assert proto.found_hosts == {"192.168.1.145": "Curtain-400"}


def test_discovered_device_display_label_with_scene_and_composition() -> None:
    """Verify DiscoveredTwinklyDevice formats scene, composition, and LED count."""
    dev = DiscoveredTwinklyDevice(
        host="192.168.1.145",
        name="Curtain-400",
        mac="40:4c:ca:11:22:33",
        uuid="uuid-curtain-400",
        product_code="TWW400SPP",
        number_of_led=400,
        led_profile="RGB",
        sync_mode="master",
        group_uid="grp_curtain",
        scene_name="Гостиная",
        composition_name="Штора Окно",
    )
    label = dev.display_label
    assert "Curtain-400" in label
    assert "400 RGB" in label
    assert "Сцена: Гостиная" in label
    assert "[Штора Окно: MASTER]" in label
    assert "IP: 192.168.1.145" in label


def test_twinkly_music_dongle_gestalt_and_cloud_parsing() -> None:
    """Verify Twinkly Music dongle (TMD01USB) parses cleanly even with null LED fields and from Cloud."""
    music_gestalt = GestaltInfo.from_dict(
        {
            "product_name": "Twinkly Music",
            "product_code": "TMD01USB",
            "fw_family": "M",
            "device_name": "Music Dongle",
            "mac": "40:4C:CA:AA:BB:CC",
            "uuid": "uuid-music-1",
            "number_of_led": None,
            "led_profile": None,
            "frame_rate": None,
        }
    )
    assert music_gestalt.is_music_dongle is True
    assert music_gestalt.number_of_led == 0
    assert music_gestalt.led_profile == "MUSIC"

    cloud_inv = {
        "devices": [
            {
                "name": "Curtain-400",
                "mac": "404cca112233",
                "uuid": "uuid-curtain",
                "product_code": "TWW400SPP",
                "number_of_led": 400,
            },
            {
                "name": "My Twinkly Music",
                "mac": "404ccaaabbcc",
                "uuid": "uuid-music-1",
                "product_code": "TMD01USB",
                "fw_family": "M",
            },
        ],
        "objects": [],
        "profile": [],
    }
    devs, _, _ = TwinklyCloudClient._parse_cloud_records(cloud_inv)
    assert len(devs) == 2
    music_dev = next(d for d in devs if d.is_music_dongle)
    assert music_dev.name == "My Twinkly Music"
    assert "🎵 My Twinkly Music" in music_dev.display_label
    assert "Twinkly Music" in music_dev.display_label


def test_device_capabilities_matrix() -> None:
    """Verify DeviceCapabilities across Gen I, Gold AWW, Squares Matrix, and Music Dongle."""
    gen1 = GestaltInfo.from_dict(
        {
            "product_code": "TWS175STP",
            "fw_family": "D",
            "number_of_led": 175,
            "led_profile": "RGB",
        }
    )
    caps_gen1 = DeviceCapabilities.from_gestalt(gen1)
    assert caps_gen1.generation == 1
    assert caps_gen1.rt_protocol_version == 1
    assert caps_gen1.supports_light is True
    assert caps_gen1.supports_multi_movies is False
    assert caps_gen1.supports_playlists is False
    assert caps_gen1.supports_music_reactive is False
    assert caps_gen1.supports_color_mode is False

    gold = GestaltInfo.from_dict(
        {
            "product_code": "TWS250GOP",
            "fw_family": "G",
            "number_of_led": 250,
            "led_profile": "AWW",
        }
    )
    caps_gold = DeviceCapabilities.from_gestalt(gold)
    assert caps_gold.generation == 2
    assert caps_gold.color_profile == "AWW"
    assert caps_gold.rt_protocol_version == 3

    squares = GestaltInfo.from_dict(
        {
            "product_code": "TWQ064STW",
            "fw_family": "G",
            "number_of_led": 256,
            "led_profile": "RGB",
        }
    )
    caps_sq = DeviceCapabilities.from_gestalt(squares)
    assert caps_sq.device_category == "wall_matrix"
    assert caps_sq.is_matrix_tiles is True
    assert caps_sq.tile_count == 4

    music = GestaltInfo.from_dict(
        {
            "product_code": "TMD01USB",
            "fw_family": "M",
            "number_of_led": 0,
        }
    )
    caps_music = DeviceCapabilities.from_gestalt(music)
    assert caps_music.device_category == "music_dongle"
    assert caps_music.supports_light is False
    assert caps_music.supports_brightness is False
    assert caps_music.supports_music_reactive is True


def test_udp_v1_packet_and_aww_movie_encoding() -> None:
    """Verify Gen I v1 UDP packet header and AWW Gold Edition movie encoding."""
    token = base64.b64decode("AAECAwQFBgc=")
    frame = bytes([255, 128, 64] * 10)  # 10 RGB LEDs
    pkts = TwinklyRealtimeStreamer.build_v1_packets(token, frame, bytes_per_led=3)
    assert len(pkts) == 1
    assert pkts[0][0] == 1
    assert pkts[0][1:9] == token
    assert pkts[0][9] == 10
    assert pkts[0][10:] == frame

    coords = DeviceLayout.create_default_tree_coordinates(15)
    raw_aww, frames_count, _ = compile_procedural_movie(
        preset="fire_flame",
        coordinates=coords,
        duration_seconds=1.0,
        fps=10,
        bytes_per_led=3,
        color_profile="AWW",
    )
    assert frames_count == 10
    assert len(raw_aww) == 10 * 15 * 3


@pytest.mark.asyncio
async def test_live_endpoint_probing_in_snapshot() -> None:
    """Verify fetch_full_snapshot probes endpoints and disables unsupported features."""

    async def handle_gestalt(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "device_name": "Gen1 String",
                "mac": "AA:11:22:33:44:55",
                "uuid": "uuid-gen1",
                "fw_family": "G",
                "number_of_led": 50,
                "led_profile": "RGB",
                "code": 1000,
            }
        )

    async def handle_login(request: web.Request) -> web.Response:
        return web.json_response({"authentication_token": "AAECAwQFBgc=", "code": 1000})

    async def handle_verify(request: web.Request) -> web.Response:
        return web.json_response({"code": 1000})

    async def handle_ok_mode(request: web.Request) -> web.Response:
        return web.json_response({"mode": "movie", "code": 1000})

    async def handle_not_found(request: web.Request) -> web.Response:
        return web.Response(status=404, text="Not supported")

    app = web.Application()
    app.router.add_get("/xled/v1/gestalt", handle_gestalt)
    app.router.add_post("/xled/v1/login", handle_login)
    app.router.add_post("/xled/v1/verify", handle_verify)
    app.router.add_get("/xled/v1/led/mode", handle_ok_mode)
    app.router.add_get("/xled/v1/movies", handle_not_found)
    app.router.add_get("/xled/v1/playlist", handle_not_found)
    app.router.add_get("/xled/v1/music/drivers", handle_not_found)
    app.router.add_get("/xled/v1/led/color", handle_not_found)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    client = TwinklyClient(host="127.0.0.1", port=port)
    try:
        snap = await client.fetch_full_snapshot()
        assert snap.capabilities.supports_multi_movies is False
        assert snap.capabilities.supports_playlists is False
        assert snap.capabilities.supports_music_reactive is False
        assert snap.capabilities.supports_color_mode is False
    finally:
        await client.close()
        await runner.cleanup()


def test_cloud_deleted_devices_filtered_and_split() -> None:
    """Verify deleted cloud devices are skipped and active ones are kept."""
    cloud_inv = {
        "devices": [
            {
                "name": "Active Garland",
                "mac": "404cca111111",
                "uuid": "uuid-active",
                "product_code": "TWS250SPP",
                "number_of_led": 250,
            },
            {
                "name": "Deleted Old Curtain",
                "mac": "404cca222222",
                "uuid": "uuid-deleted",
                "product_code": "TWW210SPP",
                "deleted": True,
            },
        ],
        "objects": [],
        "profile": [],
    }
    devs, _, _ = TwinklyCloudClient._parse_cloud_records(cloud_inv)
    assert len(devs) == 1
    assert devs[0].name == "Active Garland"


