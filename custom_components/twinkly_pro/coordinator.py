"""DataUpdateCoordinator for Twinkly Pro devices with Master/Slave group routing."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .twinkly_client import (
    TwinklyClient,
    TwinklyDeviceSnapshot,
    TwinklyError,
    TwinklyRealtimeStreamer,
    compile_custom_frames_movie,
    compile_procedural_movie,
)

_LOGGER = logging.getLogger(__name__)


class TwinklyProCoordinator(DataUpdateCoordinator[TwinklyDeviceSnapshot]):
    """Coordinator managing polling, RT streaming, and Master/Slave routing for a Twinkly device."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        host: str,
    ) -> None:
        """Initialize the Twinkly Pro coordinator."""
        self.entry = entry
        self.host = host
        session = async_get_clientsession(hass)
        self.client = TwinklyClient(host=host, session=session)
        self.streamer = TwinklyRealtimeStreamer(self.client)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{host}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return Home Assistant DeviceInfo for this Twinkly controller."""
        snap = self.data
        mac = snap.gestalt.mac if snap else self.entry.data.get("mac", self.host)
        name = (
            snap.gestalt.device_name
            if snap
            else self.entry.data.get("device_name", f"Twinkly ({self.host})")
        )
        model = (
            f"{snap.gestalt.product_code} ({snap.gestalt.number_of_led} {snap.gestalt.led_profile})"
            if snap
            else "Twinkly Smart LED"
        )
        sw_version = snap.fw_version if snap else "unknown"
        scene_area = self.entry.data.get("scene_name") or None

        return DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=name,
            manufacturer="Twinkly (Ledworks)",
            model=model,
            sw_version=sw_version,
            suggested_area=scene_area,
            configuration_url=f"http://{self.host}",
        )

    def get_target_coordinator(self) -> TwinklyProCoordinator:
        """Return the Master coordinator if this device is a Slave in a synced group.

        Ensures commands sent to a Slave device are routed to its Master controller
        so the group never loses synchronization.
        """
        if not self.data or not self.data.sync.is_slave:
            return self

        group_uid = self.data.sync.group_uid
        master_uid = self.data.sync.master_uid
        domain_data: dict[str, Any] = self.hass.data.get(DOMAIN, {})
        coordinators: dict[str, TwinklyProCoordinator] = domain_data.get(
            "coordinators", {}
        )

        for other in coordinators.values():
            if other is self or not other.data:
                continue
            if master_uid and other.data.gestalt.uuid == master_uid:
                return other
            if (
                group_uid
                and other.data.sync.group_uid == group_uid
                and other.data.sync.is_master
            ):
                return other

        return self

    async def _async_update_data(self) -> TwinklyDeviceSnapshot:
        """Fetch latest device state from the Twinkly controller."""
        try:
            snapshot = await self.client.fetch_full_snapshot()
            snapshot.is_rt_streaming = self.streamer.is_streaming
            snapshot.active_rt_preset = self.streamer.active_preset
            return snapshot
        except TwinklyError as err:
            raise UpdateFailed(f"Error communicating with Twinkly at {self.host}: {err}") from err

    async def async_shutdown(self) -> None:
        """Clean up active UDP streams when unloading."""
        await self.streamer.stop()

    # -------------------------------------------------------------------------
    # High-level actions with automatic Master routing
    # -------------------------------------------------------------------------

    async def async_set_mode(self, mode: str) -> None:
        """Set operating mode (routes to Master if device is Slave)."""
        target = self.get_target_coordinator()
        if mode != "rt" and target.streamer.is_streaming:
            await target.streamer.stop()
        await target.client.set_mode(mode)
        await target.async_request_refresh()
        if target is not self:
            await self.async_request_refresh()

    async def async_set_brightness(self, value_0_100: int) -> None:
        """Set brightness 0..100 (routes to Master if device is Slave)."""
        target = self.get_target_coordinator()
        await target.client.set_brightness(value_0_100, enabled=True)
        await target.async_request_refresh()

    async def async_set_color(
        self,
        red: int,
        green: int,
        blue: int,
        white: int | None = None,
    ) -> None:
        """Set static RGB/RGBW color (routes to Master if device is Slave)."""
        target = self.get_target_coordinator()
        if target.streamer.is_streaming:
            await target.streamer.stop()
        await target.client.set_color(
            red=red,
            green=green,
            blue=blue,
            white=white,
            switch_to_color_mode=True,
        )
        await target.async_request_refresh()

    async def async_select_movie(self, movie_id: int) -> None:
        """Activate a movie stored in flash memory."""
        target = self.get_target_coordinator()
        if target.streamer.is_streaming:
            await target.streamer.stop()
        await target.client.set_current_movie(movie_id, switch_mode=True)
        await target.async_request_refresh()

    async def async_select_playlist_item(self, item_id: int) -> None:
        """Activate a specific playlist entry by index."""
        target = self.get_target_coordinator()
        if target.streamer.is_streaming:
            await target.streamer.stop()
        await target.client.set_current_playlist_item(item_id)
        await target.async_request_refresh()

    async def async_step_playlist_or_movie(self, step: int = 1) -> None:
        """Advance to the next (+1) or previous (-1) playlist item or movie."""
        target = self.get_target_coordinator()
        snap = target.data
        if not snap:
            return

        if snap.mode == "playlist" and snap.playlist.entries:
            entries = snap.playlist.entries
            curr_idx = snap.playlist.current_id or 0
            next_idx = (curr_idx + step) % len(entries)
            await target.async_select_playlist_item(next_idx)
        elif snap.movies.movies:
            movies = snap.movies.movies
            ids = [m.id for m in movies]
            curr_id = snap.movies.current_movie_id
            curr_pos = ids.index(curr_id) if curr_id in ids else 0
            next_id = ids[(curr_pos + step) % len(ids)]
            await target.async_select_movie(next_id)

    async def async_select_music_driver(self, driver_id: int, unique_id: str = "") -> None:
        """Select a Twinkly Music driver and switch to music mode."""
        target = self.get_target_coordinator()
        if target.streamer.is_streaming:
            await target.streamer.stop()
        await target.client.set_music_driver(
            driver_id=driver_id,
            unique_id=unique_id or None,
            activate_music_mode=True,
        )
        await target.async_request_refresh()

    async def async_start_rt_effect(
        self,
        preset: str = "rainbow_wave",
        fps: int = 25,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Start live UDP Real-Time procedural streaming on this controller (and slaves if master)."""
        target = self.get_target_coordinator()
        await target.streamer.start_effect_stream(preset=preset, fps=fps, params=params)
        await target.async_request_refresh()

    async def async_stop_rt_effect(self, restore_mode: str = "movie") -> None:
        """Stop live UDP Real-Time streaming."""
        target = self.get_target_coordinator()
        await target.streamer.stop(restore_mode=restore_mode)
        await target.async_request_refresh()

    async def async_upload_generated_movie(
        self,
        name: str,
        preset: str = "rainbow_wave",
        duration_seconds: float = 6.0,
        fps: int = 20,
        params: dict[str, Any] | None = None,
        activate: bool = True,
    ) -> int:
        """Compile a 2D/3D procedural movie for this device's LED layout and upload to flash."""
        target = self.get_target_coordinator()
        if target.streamer.is_streaming:
            await target.streamer.stop()

        gestalt = await target.client.get_gestalt()
        layout = await target.client.get_layout()

        raw_bytes, frames_count, uid = compile_procedural_movie(
            preset=preset,
            coordinates=layout.coordinates,
            duration_seconds=duration_seconds,
            fps=fps,
            bytes_per_led=gestalt.bytes_per_led,
            params=params,
        )
        movie_id = await target.client.upload_movie(
            name=name,
            raw_frames=raw_bytes,
            frames_number=frames_count,
            fps=fps,
            leds_per_frame=gestalt.number_of_led,
            unique_id=uid,
            activate=activate,
        )
        await target.async_request_refresh()
        return movie_id

    async def async_upload_custom_frames_movie(
        self,
        name: str,
        frames_rgb: list[list[list[int]]],
        fps: int = 20,
        activate: bool = True,
    ) -> int:
        """Compile custom RGB frames sent from Twinkly Studio UI and upload to flash."""
        target = self.get_target_coordinator()
        if target.streamer.is_streaming:
            await target.streamer.stop()

        gestalt = await target.client.get_gestalt()
        raw_bytes, frames_count = compile_custom_frames_movie(
            frames_rgb, bytes_per_led=gestalt.bytes_per_led
        )
        movie_id = await target.client.upload_movie(
            name=name,
            raw_frames=raw_bytes,
            frames_number=frames_count,
            fps=fps,
            leds_per_frame=gestalt.number_of_led,
            unique_id=str(uuid.uuid4()),
            activate=activate,
        )
        await target.async_request_refresh()
        return movie_id
