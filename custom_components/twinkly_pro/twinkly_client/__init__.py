"""Twinkly XLED v1 client and procedural movie engine."""

from .client import (
    TwinklyAuthError,
    TwinklyClient,
    TwinklyConnectionError,
    TwinklyError,
)
from .cloud import CURATED_GALLERY_TEMPLATES, TwinklyCloudClient
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
    "DeviceBrightness",
    "DeviceColor",
    "DeviceLayout",
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
    "compile_custom_frames_movie",
    "compile_procedural_movie",
    "generate_effect_frame",
]
