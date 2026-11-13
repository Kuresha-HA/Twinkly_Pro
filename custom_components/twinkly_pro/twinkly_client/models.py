"""Data models for the Twinkly XLED v1 protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _safe_int(val: Any, default: int = 0) -> int:
    """Convert value to int safely even if val is None or empty."""
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert value to float safely even if val is None or empty."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


@dataclass(slots=True)
class GestaltInfo:
    """Hardware and profile metadata returned by /xled/v1/gestalt."""

    product_name: str = "Twinkly"
    hardware_version: str = "1"
    bytes_per_led: int = 3
    hw_id: str = ""
    flash_size: int = 0
    led_type: int = 0
    product_code: str = ""
    fw_family: str = "G"
    device_name: str = "Twinkly"
    uptime: str = "0"
    mac: str = ""
    uuid: str = ""
    max_supported_led: int = 0
    number_of_led: int = 0
    led_profile: str = "RGB"
    frame_rate: float = 25.0
    measured_frame_rate: float = 25.0
    movie_capacity: int = 0
    wire_type: int = 0

    @property
    def is_music_dongle(self) -> bool:
        """Return True if this device is a Twinkly Music USB dongle (TMD01USB)."""
        pcode = self.product_code.upper()
        pname = self.product_name.upper()
        dname = self.device_name.upper()
        return (
            self.fw_family.upper() == "M"
            or pcode.startswith("TMD")
            or "MUSIC" in pname
            or "MUSIC" in dname
            or (self.number_of_led == 0 and pcode != "")
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GestaltInfo:
        """Create GestaltInfo from API response dictionary (supports LED strings and TMD01USB Music)."""
        product_code = str(data.get("product_code") or "")
        fw_family = str(data.get("fw_family") or "G")
        product_name = str(data.get("product_name") or "Twinkly")
        is_music = (
            fw_family.upper() == "M"
            or product_code.upper().startswith("TMD")
            or "MUSIC" in product_name.upper()
        )

        led_profile = str(data.get("led_profile") or ("MUSIC" if is_music else "RGB")).upper()
        default_leds = 0 if is_music else 100
        bytes_per_led = _safe_int(
            data.get("bytes_per_led"), 4 if led_profile == "RGBW" else 3
        )
        return cls(
            product_name=product_name,
            hardware_version=str(data.get("hardware_version") or "1"),
            bytes_per_led=bytes_per_led,
            hw_id=str(data.get("hw_id") or ""),
            flash_size=_safe_int(data.get("flash_size"), 0),
            led_type=_safe_int(data.get("led_type"), 0),
            product_code=product_code,
            fw_family=fw_family,
            device_name=str(
                data.get("device_name")
                or ("Twinkly Music" if is_music else "Twinkly")
            ),
            uptime=str(data.get("uptime") or "0"),
            mac=str(data.get("mac") or "").lower(),
            uuid=str(data.get("uuid") or ""),
            max_supported_led=_safe_int(data.get("max_supported_led"), 0),
            number_of_led=_safe_int(data.get("number_of_led"), default_leds),
            led_profile=led_profile,
            frame_rate=_safe_float(data.get("frame_rate"), 25.0),
            measured_frame_rate=_safe_float(data.get("measured_frame_rate"), 25.0),
            movie_capacity=_safe_int(data.get("movie_capacity"), 0),
            wire_type=_safe_int(data.get("wire_type"), 0),
        )


@dataclass(slots=True)
class SyncInfo:
    """Group synchronization state from /xled/v1/sync."""

    mode: str = "none"  # "none", "master", "slave"
    group_uid: str = ""
    master_uid: str = ""
    slave_id: int = 0
    compat_mode: int = 0

    @property
    def is_grouped(self) -> bool:
        """Return True if device belongs to a sync group."""
        return self.mode in ("master", "slave") and bool(self.group_uid)

    @property
    def is_master(self) -> bool:
        """Return True if device is the master controller of a group."""
        return self.mode == "master"

    @property
    def is_slave(self) -> bool:
        """Return True if device is a slave member of a group."""
        return self.mode == "slave"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncInfo:
        """Parse SyncInfo from API response."""
        sync_block = data.get("sync", data)
        if not isinstance(sync_block, dict):
            return cls()
        mode = str(sync_block.get("mode") or "none").lower()
        return cls(
            mode=mode,
            group_uid=str(sync_block.get("group_uid") or sync_block.get("uid") or ""),
            master_uid=str(sync_block.get("master_uid") or ""),
            slave_id=_safe_int(sync_block.get("slave_id"), 0),
            compat_mode=_safe_int(sync_block.get("compat_mode"), 0),
        )


@dataclass(slots=True)
class DeviceBrightness:
    """Brightness state from /xled/v1/led/out/brightness."""

    enabled: bool = True
    value: int = 100  # 0..100

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceBrightness:
        """Parse brightness from API dict."""
        mode = str(data.get("mode") or "enabled").lower()
        val = _safe_int(data.get("value"), 100)
        return cls(
            enabled=(mode == "enabled"),
            value=max(0, min(100, val)),
        )


@dataclass(slots=True)
class DeviceColor:
    """Static color state from /xled/v1/led/color."""

    red: int = 255
    green: int = 255
    blue: int = 255
    white: int = 0
    hue: int = 0
    saturation: int = 0
    value: int = 255

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceColor:
        """Parse color from API dict."""
        return cls(
            red=_safe_int(data.get("red"), 255),
            green=_safe_int(data.get("green"), 255),
            blue=_safe_int(data.get("blue"), 255),
            white=_safe_int(data.get("white"), 0),
            hue=_safe_int(data.get("hue"), 0),
            saturation=_safe_int(data.get("saturation"), 0),
            value=_safe_int(data.get("value"), 255),
        )


@dataclass(slots=True)
class MovieEntry:
    """Single movie stored in device flash memory."""

    id: int
    name: str
    unique_id: str
    descriptor_type: str = "rgb_raw"
    leds_per_frame: int = 0
    frames_number: int = 0
    fps: int = 20

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MovieEntry:
        """Parse movie entry from API dict."""
        movie_id = _safe_int(data.get("id"), 0)
        unique_id = str(data.get("unique_id") or f"movie_{movie_id}")
        name = str(data.get("name") or f"Effect #{movie_id}")
        return cls(
            id=movie_id,
            name=name,
            unique_id=unique_id,
            descriptor_type=str(data.get("descriptor_type") or "rgb_raw"),
            leds_per_frame=_safe_int(data.get("leds_per_frame"), 0),
            frames_number=_safe_int(data.get("frames_number"), 0),
            fps=_safe_int(data.get("fps"), 20),
        )


@dataclass(slots=True)
class MoviesState:
    """Complete movie catalog and flash memory status."""

    movies: list[MovieEntry] = field(default_factory=list)
    available_frames: int = 0
    max_capacity: int = 0
    max_movies: int = 15
    current_movie_id: int | None = None
    current_movie_unique_id: str = ""

    @classmethod
    def from_dict(
        cls,
        movies_data: dict[str, Any],
        current_data: dict[str, Any] | None = None,
    ) -> MoviesState:
        """Parse MoviesState from /xled/v1/movies and /xled/v1/movies/current."""
        raw_list = movies_data.get("movies", [])
        entries = [
            MovieEntry.from_dict(item)
            for item in (raw_list or [])
            if isinstance(item, dict)
        ]
        curr_id: int | None = None
        curr_uid = ""
        if current_data and current_data.get("id") is not None:
            curr_id = _safe_int(current_data["id"], 0)
            curr_uid = str(current_data.get("unique_id") or "")
        return cls(
            movies=entries,
            available_frames=_safe_int(movies_data.get("available_frames"), 0),
            max_capacity=_safe_int(movies_data.get("max_capacity"), 0),
            max_movies=_safe_int(movies_data.get("max"), 15),
            current_movie_id=curr_id,
            current_movie_unique_id=curr_uid,
        )


@dataclass(slots=True)
class PlaylistEntry:
    """Single item in the device playlist."""

    unique_id: str
    duration: int = 30  # seconds
    movie_id: int | None = None
    name: str = ""

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        movies_by_uid: dict[str, MovieEntry] | None = None,
    ) -> PlaylistEntry:
        """Parse playlist entry and enrich with movie name if available."""
        uid = str(data.get("unique_id") or "")
        duration = _safe_int(data.get("duration"), 30)
        movie_id: int | None = data.get("id")
        if movie_id is not None:
            movie_id = _safe_int(movie_id, 0)
        name = str(data.get("name") or "")
        if movies_by_uid and uid in movies_by_uid:
            matched = movies_by_uid[uid]
            movie_id = matched.id
            if not name:
                name = matched.name
        if not name:
            name = f"Track ({uid[:8]})" if uid else "Track"
        return cls(
            unique_id=uid,
            duration=duration,
            movie_id=movie_id,
            name=name,
        )


@dataclass(slots=True)
class PlaylistState:
    """Device playlist configuration and active item."""

    entries: list[PlaylistEntry] = field(default_factory=list)
    current_id: int | None = None
    current_unique_id: str = ""

    @classmethod
    def from_dict(
        cls,
        playlist_data: dict[str, Any],
        current_data: dict[str, Any] | None = None,
        movies: list[MovieEntry] | None = None,
    ) -> PlaylistState:
        """Parse PlaylistState from /xled/v1/playlist and /xled/v1/playlist/current."""
        movies_by_uid = {m.unique_id: m for m in (movies or []) if m.unique_id}
        raw_entries = playlist_data.get("entries", [])
        entries = [
            PlaylistEntry.from_dict(item, movies_by_uid)
            for item in (raw_entries or [])
            if isinstance(item, dict)
        ]
        curr_id: int | None = None
        curr_uid = ""
        if current_data:
            if current_data.get("id") is not None:
                curr_id = _safe_int(current_data["id"], 0)
            curr_uid = str(current_data.get("unique_id") or "")
        return cls(
            entries=entries,
            current_id=curr_id,
            current_unique_id=curr_uid,
        )


@dataclass(slots=True)
class LedCoordinate:
    """Normalized 3D/2D coordinate of a single LED."""

    x: float
    y: float
    z: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Serialize coordinate to dict."""
        return {"x": round(self.x, 5), "y": round(self.y, 5), "z": round(self.z, 5)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LedCoordinate:
        """Create LedCoordinate from API dict."""
        return cls(
            x=_safe_float(data.get("x"), 0.0),
            y=_safe_float(data.get("y"), 0.0),
            z=_safe_float(data.get("z"), 0.0),
        )


@dataclass(slots=True)
class DeviceLayout:
    """Spatial LED layout from /xled/v1/led/layout/full."""

    source: str = "linear"  # "linear", "2d", "3d"
    synthesized: bool = True
    uuid: str = ""
    aspect_xy: int = 0
    aspect_xz: int = 0
    coordinates: list[LedCoordinate] = field(default_factory=list)

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], fallback_led_count: int = 100
    ) -> DeviceLayout:
        """Parse DeviceLayout from API response or generate default linear layout."""
        raw_coords = data.get("coordinates", [])
        coords = [
            LedCoordinate.from_dict(c)
            for c in (raw_coords or [])
            if isinstance(c, dict)
        ]
        if not coords and fallback_led_count > 0:
            coords = cls.create_default_tree_coordinates(fallback_led_count)
        return cls(
            source=str(data.get("source") or "2d"),
            synthesized=bool(data.get("synthesized", False)),
            uuid=str(data.get("uuid") or ""),
            aspect_xy=_safe_int(data.get("aspectXY"), 0),
            aspect_xz=_safe_int(data.get("aspectXZ"), 0),
            coordinates=coords,
        )

    @staticmethod
    def create_default_tree_coordinates(num_leds: int) -> list[LedCoordinate]:
        """Generate a spiral cone / tree layout when physical mapping is absent."""
        import math

        coords: list[LedCoordinate] = []
        turns = max(4.0, math.sqrt(max(1, num_leds)) * 0.6)
        for i in range(num_leds):
            t = i / max(1, num_leds - 1)
            y = t
            radius = (1.0 - t * 0.85) * 0.85
            angle = t * turns * 2.0 * math.pi
            x = math.cos(angle) * radius
            z = math.sin(angle) * radius
            coords.append(LedCoordinate(x=x, y=y, z=z))
        return coords


@dataclass(slots=True)
class MusicDriver:
    """Music reactive driver / preset on the controller."""

    id: int
    unique_id: str
    name: str
    effect_index: int = 0

    @classmethod
    def from_dict(cls, idx: int, data: dict[str, Any]) -> MusicDriver:
        """Parse MusicDriver from /xled/v1/music/drivers."""
        uid = str(data.get("unique_id") or f"driver_{idx}")
        driver_id = _safe_int(data.get("id"), idx)
        name = str(data.get("name") or f"Music Preset #{driver_id + 1}")
        return cls(
            id=driver_id,
            unique_id=uid,
            name=name,
            effect_index=_safe_int(data.get("effect_index"), idx),
        )


@dataclass(slots=True)
class MusicState:
    """Twinkly Music reactive state."""

    enabled: bool = False
    active: bool = False
    mode: str = "manual"
    auto_mode: str = "off"
    current_driver_id: int | None = None
    current_driver_unique_id: str = ""
    drivers: list[MusicDriver] = field(default_factory=list)
    sensitivity: int = 75  # 0..100

    @classmethod
    def from_dict(
        cls,
        enabled_data: dict[str, Any] | None = None,
        drivers_data: dict[str, Any] | None = None,
        current_driver_data: dict[str, Any] | None = None,
    ) -> MusicState:
        """Parse MusicState from music API responses."""
        enabled = bool((enabled_data or {}).get("enabled", False))
        active = bool((enabled_data or {}).get("active", enabled))
        mode = str((enabled_data or {}).get("mode") or "manual")
        auto_mode = str((enabled_data or {}).get("auto_mode") or "off")

        drivers: list[MusicDriver] = []
        if drivers_data and isinstance(drivers_data.get("drivers"), list):
            for idx, item in enumerate(drivers_data["drivers"]):
                if isinstance(item, dict):
                    drivers.append(MusicDriver.from_dict(idx, item))

        curr_id: int | None = None
        curr_uid = ""
        if current_driver_data:
            if current_driver_data.get("id") is not None:
                curr_id = _safe_int(current_driver_data["id"], 0)
            curr_uid = str(current_driver_data.get("unique_id") or "")

        return cls(
            enabled=enabled,
            active=active,
            mode=mode,
            auto_mode=auto_mode,
            current_driver_id=curr_id,
            current_driver_unique_id=curr_uid,
            drivers=drivers,
        )


@dataclass(slots=True)
class DeviceCapabilities:
    """Hardware and firmware capability matrix derived from gestalt and live endpoint probing."""

    generation: int = 2  # 1 (ESP8266: A/B/C/D) or 2 (ESP32: F/G/N/P)
    device_category: str = "light_string"  # light_string, wall_matrix, pro_controller, music_dongle
    color_profile: str = "RGB"  # RGB, RGBW, AWW, MUSIC
    rt_protocol_version: int = 3  # 1 (Gen I), 3 (Gen II+), 0 (unsupported)
    supports_light: bool = True
    supports_brightness: bool = True
    supports_color_mode: bool = True
    supports_multi_movies: bool = True
    supports_playlists: bool = True
    supports_music_reactive: bool = True
    supports_sync_group: bool = True
    supports_rt_streaming: bool = True
    is_matrix_tiles: bool = False
    tile_count: int = 0

    @classmethod
    def from_gestalt(
        cls,
        gestalt: GestaltInfo,
        probed: dict[str, bool] | None = None,
    ) -> DeviceCapabilities:
        """Build DeviceCapabilities from GestaltInfo and optional live-probed endpoint flags."""
        fw_family = gestalt.fw_family.upper().strip()
        pcode = gestalt.product_code.upper().strip()
        pname = gestalt.product_name.upper().strip()

        generation = 1 if fw_family in ("A", "B", "C", "D") else 2

        if gestalt.is_music_dongle:
            device_category = "music_dongle"
        elif (
            pcode.startswith(("TWQ", "TWM"))
            or "SQUARES" in pname
            or "MATRIX" in pname
        ):
            device_category = "wall_matrix"
        elif fw_family == "P" or pcode.startswith("TWPRO"):
            device_category = "pro_controller"
        else:
            device_category = "light_string"

        if device_category == "music_dongle":
            color_profile = "MUSIC"
        elif gestalt.led_profile.upper() in ("RGB", "RGBW", "AWW"):
            color_profile = gestalt.led_profile.upper()
        else:
            color_profile = "RGB"

        is_matrix = device_category == "wall_matrix"
        tile_count = (
            max(1, gestalt.number_of_led // 64)
            if is_matrix and gestalt.number_of_led > 0
            else 0
        )

        if device_category == "music_dongle":
            caps = cls(
                generation=generation,
                device_category=device_category,
                color_profile=color_profile,
                rt_protocol_version=0,
                supports_light=False,
                supports_brightness=False,
                supports_color_mode=False,
                supports_multi_movies=False,
                supports_playlists=False,
                supports_music_reactive=True,
                supports_sync_group=False,
                supports_rt_streaming=False,
                is_matrix_tiles=False,
                tile_count=0,
            )
        elif generation == 1:
            caps = cls(
                generation=1,
                device_category=device_category,
                color_profile=color_profile,
                rt_protocol_version=1,
                supports_light=True,
                supports_brightness=True,
                supports_color_mode=False,
                supports_multi_movies=False,
                supports_playlists=False,
                supports_music_reactive=False,
                supports_sync_group=True,
                supports_rt_streaming=True,
                is_matrix_tiles=is_matrix,
                tile_count=tile_count,
            )
        else:
            caps = cls(
                generation=2,
                device_category=device_category,
                color_profile=color_profile,
                rt_protocol_version=3,
                supports_light=True,
                supports_brightness=True,
                supports_color_mode=True,
                supports_multi_movies=True,
                supports_playlists=True,
                supports_music_reactive=True,
                supports_sync_group=True,
                supports_rt_streaming=True,
                is_matrix_tiles=is_matrix,
                tile_count=tile_count,
            )

        if probed and device_category != "music_dongle":
            for flag in (
                "supports_brightness",
                "supports_color_mode",
                "supports_multi_movies",
                "supports_playlists",
                "supports_music_reactive",
                "supports_sync_group",
            ):
                if flag in probed:
                    setattr(caps, flag, bool(probed[flag]))

        return caps


@dataclass(slots=True)
class TwinklyDeviceSnapshot:
    """Complete snapshot of a Twinkly device state."""

    host: str
    gestalt: GestaltInfo
    fw_version: str = "0.0.0"
    mode: str = "off"
    brightness: DeviceBrightness = field(default_factory=DeviceBrightness)
    color: DeviceColor = field(default_factory=DeviceColor)
    sync: SyncInfo = field(default_factory=SyncInfo)
    movies: MoviesState = field(default_factory=MoviesState)
    playlist: PlaylistState = field(default_factory=PlaylistState)
    music: MusicState = field(default_factory=MusicState)
    layout: DeviceLayout = field(default_factory=DeviceLayout)
    capabilities: DeviceCapabilities = field(default_factory=DeviceCapabilities)
    online: bool = True
    is_rt_streaming: bool = False
    active_rt_preset: str = ""
