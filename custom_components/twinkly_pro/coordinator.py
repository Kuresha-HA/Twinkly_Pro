"""DataUpdateCoordinator for Twinkly Pro devices with Master/Slave group routing and Cloud offline resilience."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_DEVICE_NAME,
    CONF_GROUP_UID,
    CONF_HOST,
    CONF_LED_PROFILE,
    CONF_MAC,
    CONF_NUM_LEDS,
    CONF_PRODUCT_CODE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .twinkly_client import (
    DeviceLayout,
    GestaltInfo,
    SyncInfo,
    TwinklyClient,
    TwinklyDeviceSnapshot,
    TwinklyError,
    TwinklyRealtimeStreamer,
    async_discover_lan_hosts,
    async_probe_discovered_host,
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
        self.client = TwinklyClient(host=host or "127.0.0.1", session=session)
        self.streamer = TwinklyRealtimeStreamer(self.client)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.unique_id or host}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    @property
    def is_music_dongle(self) -> bool:
        """Return True if this coordinator manages a Twinkly Music USB dongle (TMD01USB)."""
        if self.data and self.data.gestalt.is_music_dongle:
            return True
        pcode = str(self.entry.data.get(CONF_PRODUCT_CODE, "")).upper()
        profile = str(self.entry.data.get(CONF_LED_PROFILE, "")).upper()
        dname = str(self.entry.data.get(CONF_DEVICE_NAME, "")).lower()
        return (
            pcode.startswith("TMD")
            or profile == "MUSIC"
            or "twinkly music" in dname
        )

    def _build_offline_snapshot(self) -> TwinklyDeviceSnapshot:
        """Build a fallback snapshot from ConfigEntry metadata when a Cloud device is unplugged/offline."""
        d = self.entry.data
        leds = int(d.get(CONF_NUM_LEDS, 0))
        pcode = str(d.get(CONF_PRODUCT_CODE, ""))
        profile = str(d.get(CONF_LED_PROFILE, "RGB"))
        name = str(d.get(CONF_DEVICE_NAME, "Twinkly"))
        mac = str(d.get(CONF_MAC, ""))
        group_uid = str(d.get(CONF_GROUP_UID, ""))

        gestalt = GestaltInfo(
            product_name="Twinkly Music" if pcode.upper().startswith("TMD") else "Twinkly",
            product_code=pcode,
            device_name=name,
            mac=mac,
            uuid=self.entry.unique_id or mac,
            number_of_led=leds,
            led_profile=profile,
            bytes_per_led=4 if profile == "RGBW" else 3,
        )
        sync = SyncInfo(
            mode="master" if group_uid else "none",
            group_uid=group_uid,
        )
        layout = DeviceLayout(
            source="3d",
            synthesized=True,
            coordinates=DeviceLayout.create_default_tree_coordinates(leds) if leds > 0 else [],
        )
        return TwinklyDeviceSnapshot(
            host=self.host,
            gestalt=gestalt,
            fw_version="offline",
            mode="off",
            sync=sync,
            layout=layout,
            online=False,
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return Home Assistant DeviceInfo for this Twinkly controller or Music dongle."""
        snap = self.data
        mac = (
            snap.gestalt.mac
            if snap and snap.gestalt.mac
            else self.entry.data.get(CONF_MAC, self.entry.unique_id or self.host)
        )
        name = (
            snap.gestalt.device_name
            if snap and snap.gestalt.device_name
            else self.entry.data.get(CONF_DEVICE_NAME, f"Twinkly ({self.host})")
        )
        if snap and snap.gestalt.is_music_dongle:
            model = f"Twinkly Music Dongle ({snap.gestalt.product_code or 'TMD01USB'})"
        elif snap:
            model = f"{snap.gestalt.product_code or 'Twinkly'} ({snap.gestalt.number_of_led} {snap.gestalt.led_profile})"
        else:
            model = "Twinkly Smart LED"

        sw_version = snap.fw_version if snap else "unknown"
        scene_area = self.entry.data.get("scene_name") or None
        config_url = f"http://{self.host}" if self.host else None

        return DeviceInfo(
            identifiers={(DOMAIN, str(mac).lower())},
            name=name,
            manufacturer="Twinkly (Ledworks)",
            model=model,
            sw_version=sw_version,
            suggested_area=scene_area,
            configuration_url=config_url,
        )

    def get_target_coordinator(self) -> TwinklyProCoordinator:
        """Return the Master coordinator if this device is a Slave in a synced group."""
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

    async def _async_try_resolve_missing_host(self) -> bool:
        """Attempt to find local IP via UDP 5555 broadcast if device was added from Cloud without IP."""
        target_mac = str(self.entry.data.get(CONF_MAC, "")).lower()
        target_name = str(self.entry.data.get(CONF_DEVICE_NAME, "")).lower()
        lan_hosts = await async_discover_lan_hosts(timeout=1.0)
        session = async_get_clientsession(self.hass)

        for ip, adv_name in lan_hosts.items():
            if target_name and adv_name.lower() == target_name:
                self.update_host(ip)
                return True
            probed = await async_probe_discovered_host(ip, session=session)
            if probed and target_mac and probed.unique_id == target_mac:
                self.update_host(ip)
                return True
        return False

    def update_host(self, new_host: str) -> None:
        """Update device IP address dynamically when discovered on LAN."""
        if not new_host or new_host == self.host:
            return
        self.host = new_host
        session = async_get_clientsession(self.hass)
        self.client = TwinklyClient(host=new_host, session=session)
        self.streamer = TwinklyRealtimeStreamer(self.client)
        new_data = dict(self.entry.data)
        new_data[CONF_HOST] = new_host
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)

    async def _async_update_data(self) -> TwinklyDeviceSnapshot:
        """Fetch latest device state from the Twinkly controller (gracefully handles offline Cloud devices)."""
        if not self.host:
            resolved = await self._async_try_resolve_missing_host()
            if not resolved:
                return self._build_offline_snapshot()

        try:
            snapshot = await self.client.fetch_full_snapshot()
            snapshot.is_rt_streaming = self.streamer.is_streaming
            snapshot.active_rt_preset = self.streamer.active_preset
            return snapshot
        except TwinklyError:
            # Return offline snapshot with cached metadata instead of crashing setup
            if self.data is not None:
                self.data.online = False
                return self.data
            return self._build_offline_snapshot()

    async def async_shutdown(self) -> None:
        """Clean up active UDP streams when unloading."""
        await self.streamer.stop()

    # -------------------------------------------------------------------------
    # High-level actions with automatic Master routing
    # -------------------------------------------------------------------------

    async def async_set_mode(self, mode: str) -> None:
        """Set operating mode (routes to Master if device is Slave)."""
        target = self.get_target_coordinator()
        if not target.host:
            return
        if mode != "rt" and target.streamer.is_streaming:
            await target.streamer.stop()
        await target.client.set_mode(mode)
        await target.async_request_refresh()
        if target is not self:
            await self.async_request_refresh()

    async def async_set_brightness(self, value_0_100: int) -> None:
        """Set brightness 0..100 (routes to Master if device is Slave)."""
        target = self.get_target_coordinator()
        if not target.host:
            return
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
        if not target.host:
            return
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
        if not target.host:
            return
        if target.streamer.is_streaming:
            await target.streamer.stop()
        await target.client.set_current_movie(movie_id, switch_mode=True)
        await target.async_request_refresh()

    async def async_select_playlist_item(self, item_id: int) -> None:
        """Activate a specific playlist entry by index."""
        target = self.get_target_coordinator()
        if not target.host:
            return
        if target.streamer.is_streaming:
            await target.streamer.stop()
        await target.client.set_current_playlist_item(item_id)
        await target.async_request_refresh()

    async def async_step_playlist_or_movie(self, step: int = 1) -> None:
        """Advance to the next (+1) or previous (-1) playlist item or movie."""
        target = self.get_target_coordinator()
        snap = target.data
        if not snap or not target.host:
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

    async def async_select_music_driver(
        self, driver_id: int, unique_id: str = ""
    ) -> None:
        """Select a Twinkly Music driver and switch to music mode."""
        target = self.get_target_coordinator()
        if not target.host:
            return
        if target.streamer.is_streaming:
            await target.streamer.stop()
        await target.client.set_music_driver(
            driver_id=driver_id,
            unique_id=unique_id or None,
            activate_music_mode=True,
        )
        await target.async_request_refresh()

    async def async_set_mic_sensitivity(self, sensitivity_0_100: int) -> None:
        """Set microphone sensitivity (0..100%) on Twinkly Music dongle."""
        clamped = max(0, min(100, int(sensitivity_0_100)))
        if self.data:
            self.data.music.sensitivity = clamped
        if self.host:
            try:
                await self.client._request(
                    "POST",
                    "music/sensitivity",
                    json_data={"sensitivity": clamped},
                )
            except TwinklyError:
                pass
        self.async_update_listeners()

    async def async_step_music_driver(self, step: int = 1) -> None:
        """Cycle to next (+1) or previous (-1) music preset on Twinkly Music dongle."""
        snap = self.data
        if not snap or not self.host:
            return
        drivers = snap.music.drivers
        if not drivers:
            await self.client.set_music_enabled(True)
            await self.async_request_refresh()
            return
        ids = [d.id for d in drivers]
        curr_id = snap.music.current_driver_id
        curr_pos = ids.index(curr_id) if curr_id in ids else 0
        next_driver = drivers[(curr_pos + step) % len(drivers)]
        await self.async_select_music_driver(next_driver.id, next_driver.unique_id)

    async def async_start_rt_effect(
        self,
        preset: str = "rainbow_wave",
        fps: int = 25,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Start live UDP Real-Time procedural streaming on this controller."""
        target = self.get_target_coordinator()
        if not target.host:
            return
        await target.streamer.start_effect_stream(preset=preset, fps=fps, params=params)
        await target.async_request_refresh()

    async def async_stop_rt_effect(self, restore_mode: str = "movie") -> None:
        """Stop live UDP Real-Time streaming."""
        target = self.get_target_coordinator()
        if not target.host:
            return
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
