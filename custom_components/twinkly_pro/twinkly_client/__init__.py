"""Twinkly XLED v1 client, LAN UDP discovery, Cloud sync, and procedural movie engine."""

from .client import (
    TwinklyAuthError,
    TwinklyClient,
    TwinklyConnectionError,
    TwinklyError,
)
from .cloud import (
    CURATED_GALLERY_TEMPLATES,
    CloudAccountResult,
    TwinklyCloudClient,
)
from .discovery import (
    DiscoveredTwinklyDevice,
    async_discover_lan_hosts,
    async_discover_twinkly_devices,
    async_probe_discovered_host,
)
from .models import (
    DeviceBrightness,
    DeviceColor,
    DeviceLayout,
    GestaltInfo,
    LedCoordinate,
    MovieEntry,
    MoviesState,
    MusicDriver,
    MusicState,
    PlaylistEntry,
    PlaylistState,
    SyncInfo,
    TwinklyDeviceSnapshot,
)
from .movie_encoder import (
    compile_custom_frames_movie,
    compile_procedural_movie,
    generate_effect_frame,
)
from .rt_udp import TwinklyRealtimeStreamer

__all__ = [
    "CURATED_GALLERY_TEMPLATES",
    "CloudAccountResult",
    "DeviceBrightness",
    "DeviceColor",
    "DeviceLayout",
    "DiscoveredTwinklyDevice",
    "GestaltInfo",
    "LedCoordinate",
    "MovieEntry",
    "MoviesState",
    "MusicDriver",
    "MusicState",
    "PlaylistEntry",
    "PlaylistState",
    "SyncInfo",
    "TwinklyAuthError",
    "TwinklyClient",
    "TwinklyCloudClient",
    "TwinklyConnectionError",
    "TwinklyDeviceSnapshot",
    "TwinklyError",
    "TwinklyRealtimeStreamer",
    "async_discover_lan_hosts",
    "async_discover_twinkly_devices",
    "async_probe_discovered_host",
    "compile_custom_frames_movie",
    "compile_procedural_movie",
    "generate_effect_frame",
]
