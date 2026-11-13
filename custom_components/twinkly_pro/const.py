"""Constants for the Twinkly Pro integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "twinkly_pro"
NAME: Final = "Twinkly Pro"
VERSION: Final = "0.3.1"

# Configuration keys
CONF_HOST: Final = "host"
CONF_MAC: Final = "mac"
CONF_DEVICE_NAME: Final = "device_name"
CONF_PRODUCT_CODE: Final = "product_code"
CONF_HW_ID: Final = "hw_id"
CONF_LED_PROFILE: Final = "led_profile"
CONF_NUM_LEDS: Final = "number_of_led"
CONF_CLOUD_EMAIL: Final = "cloud_email"
CONF_CLOUD_PASSWORD: Final = "cloud_password"
CONF_SKIP_CLOUD: Final = "skip_cloud"
CONF_SELECTED_DEVICES: Final = "selected_devices"
CONF_SELECTED_CLOUD_DEVICES: Final = "selected_cloud_devices"
CONF_SELECTED_LAN_DEVICES: Final = "selected_lan_devices"
CONF_ADD_MANUAL_IP: Final = "add_manual_ip"
CONF_SKIP_MANUAL: Final = "skip_manual"
CONF_SCENE_NAME: Final = "scene_name"
CONF_COMPOSITION_NAME: Final = "composition_name"
CONF_GROUP_UID: Final = "group_uid"
CONF_ENABLE_PANEL: Final = "enable_panel"

# Default values
DEFAULT_PORT: Final = 80
UDP_RT_PORT: Final = 7777
DEFAULT_SCAN_INTERVAL: Final = 10  # seconds

# Twinkly operating modes
MODE_OFF: Final = "off"
MODE_COLOR: Final = "color"
MODE_DEMO: Final = "demo"
MODE_MOVIE: Final = "movie"
MODE_PLAYLIST: Final = "playlist"
MODE_MUSIC: Final = "music"
MODE_RT: Final = "rt"
MODE_EFFECT: Final = "effect"

ALL_MODES: Final[list[str]] = [
    MODE_OFF,
    MODE_COLOR,
    MODE_MOVIE,
    MODE_PLAYLIST,
    MODE_MUSIC,
    MODE_RT,
    MODE_DEMO,
]

# Group sync roles
SYNC_MODE_NONE: Final = "none"
SYNC_MODE_MASTER: Final = "master"
SYNC_MODE_SLAVE: Final = "slave"

# LED Profiles
LED_PROFILE_RGB: Final = "RGB"
LED_PROFILE_RGBW: Final = "RGBW"
LED_PROFILE_AWW: Final = "AWW"

# Built-in procedural effects for generator & RT streaming
EFFECT_RAINBOW_WAVE: Final = "rainbow_wave"
EFFECT_GRADIENT_FLOW: Final = "gradient_flow"
EFFECT_PLASMA_2D: Final = "plasma_2d"
EFFECT_SPARKLE_TWINKLE: Final = "sparkle_twinkle"
EFFECT_FIRE_FLAME: Final = "fire_flame"
EFFECT_EQUALIZER_BARS: Final = "equalizer_bars"
EFFECT_MATRIX_RAIN: Final = "matrix_rain"
EFFECT_AURORA_BOREALIS: Final = "aurora_borealis"

BUILTIN_EFFECT_PRESETS: Final[dict[str, str]] = {
    EFFECT_RAINBOW_WAVE: "Rainbow Wave (2D/3D)",
    EFFECT_GRADIENT_FLOW: "Gradient Flow",
    EFFECT_PLASMA_2D: "Cyber Plasma",
    EFFECT_SPARKLE_TWINKLE: "Starlight Sparkle",
    EFFECT_FIRE_FLAME: "Warm Fireplace",
    EFFECT_EQUALIZER_BARS: "Audio Equalizer Bars",
    EFFECT_MATRIX_RAIN: "Emerald Matrix Rain",
    EFFECT_AURORA_BOREALIS: "Aurora Borealis",
}

# Services
SERVICE_SET_MODE: Final = "set_mode"
SERVICE_UPLOAD_GENERATED_MOVIE: Final = "upload_generated_movie"
SERVICE_SET_PLAYLIST: Final = "set_playlist"
SERVICE_START_RT_EFFECT: Final = "start_rt_effect"
SERVICE_STOP_RT_EFFECT: Final = "stop_rt_effect"
SERVICE_CONFIGURE_SYNC_GROUP: Final = "configure_sync_group"

# Panel configuration
PANEL_URL_PATH: Final = "twinkly-pro"
PANEL_TITLE: Final = "Twinkly Studio"
PANEL_ICON: Final = "mdi:string-lights"
PANEL_STATIC_PATH: Final = "/twinkly_pro_static"
