"""Light platform for Twinkly Pro."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BUILTIN_EFFECT_PRESETS,
    DOMAIN,
    LED_PROFILE_AWW,
    LED_PROFILE_RGBW,
    MODE_OFF,
)
from .coordinator import TwinklyProCoordinator

EFFECT_PREFIX_MOVIE = "Movie: "
EFFECT_PREFIX_RT = "Live RT: "
EFFECT_PLAYLIST_QUEUE = "Playlist Queue"
EFFECT_MUSIC_REACTIVE = "Twinkly Music Reactive"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Twinkly Pro Light entity if supported by device capabilities."""
    coordinator: TwinklyProCoordinator = hass.data[DOMAIN]["coordinators"][
        entry.entry_id
    ]
    if not coordinator.capabilities.supports_light:
        return
    async_add_entities([TwinklyProLight(coordinator)])


class TwinklyProLight(CoordinatorEntity[TwinklyProCoordinator], LightEntity):
    """Representation of a Twinkly Pro Smart LED string/curtain/tree."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_min_color_temp_kelvin = 1800
    _attr_max_color_temp_kelvin = 6500

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize the Twinkly Pro light entity."""
        super().__init__(coordinator)
        mac = (
            coordinator.data.gestalt.mac
            if coordinator.data
            else coordinator.entry.data.get("mac", coordinator.host)
        )
        self._attr_unique_id = f"{mac}_light"
        self._attr_device_info = coordinator.device_info

    @property
    def _led_profile(self) -> str:
        """Return device LED profile (RGB or RGBW)."""
        if self.coordinator.data:
            return self.coordinator.data.gestalt.led_profile
        return str(self.coordinator.entry.data.get("led_profile", "RGB"))

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Return supported color modes based on DeviceCapabilities."""
        caps = self.coordinator.capabilities
        if not caps.supports_color_mode:
            if caps.supports_brightness:
                return {ColorMode.BRIGHTNESS}
            return {ColorMode.ONOFF}
        if caps.color_profile == LED_PROFILE_RGBW:
            return {ColorMode.RGBW}
        if caps.color_profile == LED_PROFILE_AWW:
            return {ColorMode.COLOR_TEMP}
        return {ColorMode.RGB}

    @property
    def color_mode(self) -> ColorMode:
        """Return active color mode."""
        caps = self.coordinator.capabilities
        if not caps.supports_color_mode:
            return (
                ColorMode.BRIGHTNESS if caps.supports_brightness else ColorMode.ONOFF
            )
        if caps.color_profile == LED_PROFILE_RGBW:
            return ColorMode.RGBW
        if caps.color_profile == LED_PROFILE_AWW:
            return ColorMode.COLOR_TEMP
        return ColorMode.RGB

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return color temperature in Kelvin for Gold Edition (AWW) devices."""
        if self.coordinator.capabilities.color_profile != LED_PROFILE_AWW:
            return None
        snap = self.coordinator.data
        if not snap:
            return 2700
        # AWW maps red->Amber (1800K), green->Warm White (3200K), blue->Cold White (6500K)
        amber = snap.color.red
        cold = snap.color.blue
        total = max(1, amber + snap.color.green + cold)
        ratio = (cold - amber) / float(total)  # -1.0 (amber) .. +1.0 (cold)
        kelvin = int(3500 + ratio * 2300)
        return max(1800, min(6500, kelvin))

    @property
    def is_on(self) -> bool:
        """Return True if the Twinkly controller is on."""
        snap = self.coordinator.data
        if not snap:
            return False
        return snap.mode != MODE_OFF

    @property
    def brightness(self) -> int:
        """Return the brightness of the light between 0..255."""
        snap = self.coordinator.data
        if not snap:
            return 255
        if not snap.brightness.enabled:
            return 255
        return round((snap.brightness.value / 100.0) * 255)

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the RGB color value."""
        snap = self.coordinator.data
        if not snap:
            return (255, 255, 255)
        return (snap.color.red, snap.color.green, snap.color.blue)

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        """Return the RGBW color value."""
        snap = self.coordinator.data
        if not snap:
            return (255, 255, 255, 0)
        return (snap.color.red, snap.color.green, snap.color.blue, snap.color.white)

    @property
    def effect_list(self) -> list[str]:
        """Return the list of supported effects filtered by DeviceCapabilities."""
        effects: list[str] = []
        caps = self.coordinator.capabilities
        snap = self.coordinator.data
        if snap:
            if caps.supports_multi_movies:
                for movie in snap.movies.movies:
                    effects.append(f"{EFFECT_PREFIX_MOVIE}{movie.id}: {movie.name}")
            if caps.supports_playlists and snap.playlist.entries:
                effects.append(EFFECT_PLAYLIST_QUEUE)
        if caps.supports_music_reactive:
            effects.append(EFFECT_MUSIC_REACTIVE)
        if caps.supports_rt_streaming:
            for label in BUILTIN_EFFECT_PRESETS.values():
                effects.append(f"{EFFECT_PREFIX_RT}{label}")
        return effects

    @property
    def effect(self) -> str | None:
        """Return the currently active effect."""
        snap = self.coordinator.data
        if not snap or snap.mode == MODE_OFF:
            return None

        if snap.is_rt_streaming and snap.active_rt_preset:
            label = BUILTIN_EFFECT_PRESETS.get(
                snap.active_rt_preset, snap.active_rt_preset
            )
            return f"{EFFECT_PREFIX_RT}{label}"

        if snap.mode == "playlist":
            return EFFECT_PLAYLIST_QUEUE

        if snap.mode == "music":
            return EFFECT_MUSIC_REACTIVE

        if snap.mode == "movie":
            curr_id = snap.movies.current_movie_id
            for movie in snap.movies.movies:
                if movie.id == curr_id:
                    return f"{EFFECT_PREFIX_MOVIE}{movie.id}: {movie.name}"
            if snap.movies.movies:
                first = snap.movies.movies[0]
                return f"{EFFECT_PREFIX_MOVIE}{first.id}: {first.name}"

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return rich state attributes including capabilities, group role, and memory."""
        snap = self.coordinator.data
        if not snap:
            return {}
        caps = self.coordinator.capabilities
        attrs: dict[str, Any] = {
            "operating_mode": snap.mode,
            "generation": caps.generation,
            "device_category": caps.device_category,
            "rt_protocol_version": caps.rt_protocol_version,
            "sync_role": snap.sync.mode,
            "group_uid": snap.sync.group_uid,
            "is_rt_streaming": snap.is_rt_streaming,
            "active_rt_preset": snap.active_rt_preset,
            "stored_movies_count": len(snap.movies.movies),
            "playlist_entries_count": len(snap.playlist.entries),
            "number_of_led": snap.gestalt.number_of_led,
            "led_profile": snap.gestalt.led_profile,
            "layout_source": snap.layout.source,
        }
        if caps.is_matrix_tiles:
            attrs["tile_count"] = caps.tile_count
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the Twinkly light on with optional brightness, color, color_temp, or effect."""
        caps = self.coordinator.capabilities
        if ATTR_BRIGHTNESS in kwargs and caps.supports_brightness:
            bri_255 = int(kwargs[ATTR_BRIGHTNESS])
            bri_100 = max(1, round((bri_255 / 255.0) * 100))
            await self.coordinator.async_set_brightness(bri_100)

        if ATTR_COLOR_TEMP_KELVIN in kwargs and caps.supports_color_mode:
            kelvin = max(1800, min(6500, int(kwargs[ATTR_COLOR_TEMP_KELVIN])))
            # Convert 1800K..6500K to Amber (R), Warm White (G), Cold White (B)
            t = (kelvin - 1800) / float(6500 - 1800)  # 0.0 (amber) .. 1.0 (cold)
            amber = int(max(0, min(255, (1.0 - t) * 255)))
            warm_white = int(max(0, min(255, (1.0 - abs(t - 0.45) * 1.5) * 255)))
            cold_white = int(max(0, min(255, t * 255)))
            await self.coordinator.async_set_color(amber, warm_white, cold_white)
            return

        if ATTR_RGBW_COLOR in kwargs and caps.supports_color_mode:
            r, g, b, w = kwargs[ATTR_RGBW_COLOR]
            await self.coordinator.async_set_color(r, g, b, w)
            return

        if ATTR_RGB_COLOR in kwargs and caps.supports_color_mode:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            await self.coordinator.async_set_color(r, g, b)
            return

        if ATTR_EFFECT in kwargs:
            effect_str = str(kwargs[ATTR_EFFECT])
            await self._async_apply_effect_string(effect_str)
            return

        # Default turn on if currently off
        snap = self.coordinator.data
        if not snap or snap.mode == MODE_OFF:
            if caps.supports_playlists and snap and snap.playlist.entries:
                await self.coordinator.async_set_mode("playlist")
            elif snap and snap.movies.movies:
                await self.coordinator.async_set_mode("movie")
            elif caps.supports_color_mode:
                await self.coordinator.async_set_mode("color")
            else:
                await self.coordinator.async_set_mode("movie")

    async def _async_apply_effect_string(self, effect_str: str) -> None:
        """Parse and activate an effect selected from the Light entity."""
        if effect_str == EFFECT_PLAYLIST_QUEUE:
            await self.coordinator.async_set_mode("playlist")
            return

        if effect_str == EFFECT_MUSIC_REACTIVE:
            await self.coordinator.async_set_mode("music")
            return

        if effect_str.startswith(EFFECT_PREFIX_MOVIE):
            remainder = effect_str[len(EFFECT_PREFIX_MOVIE) :]
            movie_id_str = remainder.split(":", 1)[0].strip()
            if movie_id_str.isdigit():
                await self.coordinator.async_select_movie(int(movie_id_str))
            return

        if effect_str.startswith(EFFECT_PREFIX_RT):
            label = effect_str[len(EFFECT_PREFIX_RT) :].strip()
            for preset_key, preset_label in BUILTIN_EFFECT_PRESETS.items():
                if preset_label == label or preset_key == label:
                    await self.coordinator.async_start_rt_effect(preset=preset_key)
                    return

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the Twinkly light."""
        await self.coordinator.async_set_mode(MODE_OFF)
