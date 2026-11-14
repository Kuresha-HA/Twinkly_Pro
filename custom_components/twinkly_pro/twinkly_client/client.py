"""Asynchronous Twinkly XLED v1 REST API client."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import uuid
from typing import Any

import aiohttp

from .models import (
    DeviceBrightness,
    DeviceCapabilities,
    DeviceColor,
    DeviceLayout,
    GestaltInfo,
    LedCoordinate,
    MovieEntry,
    MoviesState,
    MusicState,
    PlaylistState,
    SyncInfo,
    TwinklyDeviceSnapshot,
)

_LOGGER = logging.getLogger(__name__)


class TwinklyError(Exception):
    """Base exception for Twinkly API errors."""


class TwinklyConnectionError(TwinklyError):
    """Raised when connection to the Twinkly controller fails."""


class TwinklyAuthError(TwinklyError):
    """Raised when authentication with the Twinkly controller fails."""


class TwinklyClient:
    """Async client for communicating with a Twinkly controller over local HTTP REST."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession | None = None,
        port: int = 80,
        timeout: float = 8.0,
    ) -> None:
        """Initialize the Twinkly client."""
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}/xled/v1"
        self._session = session
        self._owns_session = session is None
        self._timeout = aiohttp.ClientTimeout(total=timeout)

        self._auth_token: str | None = None
        self._raw_token: bytes | None = None
        self._auth_lock = asyncio.Lock()

        # Cached static or semi-static data
        self._cached_gestalt: GestaltInfo | None = None
        self._cached_fw_version: str | None = None
        self._cached_layout: DeviceLayout | None = None
        self._probed_features: dict[str, bool] = {}
        self._software_sync: SyncInfo = SyncInfo()

    @property
    def raw_token(self) -> bytes | None:
        """Return the raw 8-byte decoded authentication token for UDP RT packets."""
        return self._raw_token

    @property
    def auth_token(self) -> str | None:
        """Return the base64 authentication token string."""
        return self._auth_token

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure an aiohttp ClientSession exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Close the underlying HTTP session if owned by this client."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def authenticate(self) -> str:
        """Perform challenge-response login and verification against /xled/v1/login."""
        async with self._auth_lock:
            session = await self._ensure_session()
            challenge_bytes = os.urandom(32)
            challenge_b64 = base64.b64encode(challenge_bytes).decode("ascii")

            try:
                async with session.post(
                    f"{self.base_url}/login",
                    json={"challenge": challenge_b64},
                    timeout=self._timeout,
                ) as resp:
                    if resp.status != 200:
                        raise TwinklyAuthError(
                            f"Login failed on {self.host} with HTTP {resp.status}"
                        )
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise TwinklyConnectionError(
                    f"Cannot connect to Twinkly at {self.host}: {err}"
                ) from err

            token = data.get("authentication_token")
            if not token:
                raise TwinklyAuthError(
                    f"No authentication_token returned by {self.host}: {data}"
                )

            self._auth_token = str(token)
            try:
                self._raw_token = base64.b64decode(self._auth_token)
            except Exception:
                self._raw_token = self._auth_token.encode("utf-8")[:8].ljust(8, b"\x00")

            challenge_response = data.get("challenge-response")
            verify_payload: dict[str, Any] = {}
            if challenge_response:
                verify_payload["challenge-response"] = challenge_response

            try:
                async with session.post(
                    f"{self.base_url}/verify",
                    headers={"X-Auth-Token": self._auth_token},
                    json=verify_payload,
                    timeout=self._timeout,
                ) as verify_resp:
                    if verify_resp.status != 200:
                        _LOGGER.debug(
                            "Verify returned HTTP %s on %s, proceeding with token",
                            verify_resp.status,
                            self.host,
                        )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise TwinklyConnectionError(
                    f"Failed during token verification on {self.host}: {err}"
                ) from err

            return self._auth_token

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json_data: dict[str, Any] | None = None,
        raw_data: bytes | None = None,
        content_type: str | None = None,
        authenticated: bool = True,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        """Execute an HTTP request against the Twinkly device."""
        session = await self._ensure_session()
        if authenticated and not self._auth_token:
            await self.authenticate()

        headers: dict[str, str] = {}
        if authenticated and self._auth_token:
            headers["X-Auth-Token"] = self._auth_token
        if content_type:
            headers["Content-Type"] = content_type

        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            async with session.request(
                method,
                url,
                headers=headers,
                json=json_data,
                data=raw_data,
                timeout=self._timeout,
            ) as resp:
                if resp.status == 401 and authenticated and retry_auth:
                    _LOGGER.debug("Token expired on %s, re-authenticating", self.host)
                    self._auth_token = None
                    await self.authenticate()
                    return await self._request(
                        method,
                        endpoint,
                        json_data=json_data,
                        raw_data=raw_data,
                        content_type=content_type,
                        authenticated=authenticated,
                        retry_auth=False,
                    )

                if resp.status >= 400:
                    text = await resp.text()
                    raise TwinklyError(
                        f"HTTP {resp.status} on {method} {endpoint} ({self.host}): {text}"
                    )

                try:
                    result = await resp.json(content_type=None)
                except Exception:
                    return {"code": 1000}

                if isinstance(result, dict):
                    code = result.get("code", 1000)
                    if code == 1101 and authenticated and retry_auth:
                        # Invalid token error code in XLED body
                        self._auth_token = None
                        await self.authenticate()
                        return await self._request(
                            method,
                            endpoint,
                            json_data=json_data,
                            raw_data=raw_data,
                            content_type=content_type,
                            authenticated=authenticated,
                            retry_auth=False,
                        )
                    return result
                return {"code": 1000, "data": result}

        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise TwinklyConnectionError(
                f"Request {method} {endpoint} failed on {self.host}: {err}"
            ) from err

    # -------------------------------------------------------------------------
    # Device identity & metadata
    # -------------------------------------------------------------------------

    async def get_gestalt(self, force_refresh: bool = False) -> GestaltInfo:
        """Fetch hardware and LED configuration from /xled/v1/gestalt."""
        if self._cached_gestalt is not None and not force_refresh:
            return self._cached_gestalt
        data = await self._request("GET", "gestalt", authenticated=False)
        self._cached_gestalt = GestaltInfo.from_dict(data)
        return self._cached_gestalt

    async def get_firmware_version(self, force_refresh: bool = False) -> str:
        """Fetch firmware version string from /xled/v1/fw/version."""
        if self._cached_fw_version is not None and not force_refresh:
            return self._cached_fw_version
        try:
            data = await self._request("GET", "fw/version", authenticated=False)
            self._cached_fw_version = str(data.get("version", "0.0.0"))
        except TwinklyError:
            self._cached_fw_version = "unknown"
        return self._cached_fw_version

    async def set_device_name(self, name: str) -> None:
        """Update the friendly device name stored on the controller."""
        await self._request("POST", "device_name", json_data={"name": name[:32]})
        if self._cached_gestalt:
            self._cached_gestalt.device_name = name[:32]

    # -------------------------------------------------------------------------
    # Operating mode, brightness, and static color
    # -------------------------------------------------------------------------

    async def get_mode(self) -> str:
        """Get current operating mode (off, color, movie, playlist, music, rt, demo)."""
        try:
            data = await self._request("GET", "led/mode")
            return str(data.get("mode", "off")).lower()
        except TwinklyError:
            # Twinkly Music dongle (TMD01USB) does not have /xled/v1/led/mode
            if self._cached_gestalt and self._cached_gestalt.is_music_dongle:
                return "music"
            return "off"

    async def set_mode(self, mode: str, effect_id: int | None = None) -> None:
        """Set device operating mode."""
        payload: dict[str, Any] = {"mode": mode.lower()}
        if effect_id is not None:
            payload["effect_id"] = effect_id
        await self._request("POST", "led/mode", json_data=payload)

    async def turn_off(self) -> None:
        """Turn off the Twinkly lights."""
        await self.set_mode("off")

    async def get_brightness(self) -> DeviceBrightness:
        """Get current master brightness."""
        try:
            data = await self._request("GET", "led/out/brightness")
            if data.get("code", 1000) != 1000:
                self._probed_features["supports_brightness"] = False
                return DeviceBrightness(enabled=True, value=100)
            self._probed_features["supports_brightness"] = True
            return DeviceBrightness.from_dict(data)
        except TwinklyConnectionError:
            return DeviceBrightness(enabled=True, value=100)
        except TwinklyError:
            self._probed_features["supports_brightness"] = False
            return DeviceBrightness(enabled=True, value=100)

    async def set_brightness(self, value: int, enabled: bool = True) -> None:
        """Set master brightness (0-100)."""
        clamped = max(0, min(100, int(value)))
        await self._request(
            "POST",
            "led/out/brightness",
            json_data={
                "mode": "enabled" if enabled else "disabled",
                "type": "A",
                "value": clamped,
            },
        )

    async def get_color(self) -> DeviceColor:
        """Get static color settings."""
        try:
            data = await self._request("GET", "led/color")
            if data.get("code", 1000) != 1000:
                self._probed_features["supports_color_mode"] = False
                return DeviceColor()
            self._probed_features["supports_color_mode"] = True
            return DeviceColor.from_dict(data)
        except TwinklyConnectionError:
            return DeviceColor()
        except TwinklyError:
            self._probed_features["supports_color_mode"] = False
            return DeviceColor()

    async def set_color(
        self,
        red: int,
        green: int,
        blue: int,
        white: int | None = None,
        switch_to_color_mode: bool = True,
    ) -> None:
        """Set static RGB or RGBW color on the device."""
        payload: dict[str, int] = {
            "red": max(0, min(255, int(red))),
            "green": max(0, min(255, int(green))),
            "blue": max(0, min(255, int(blue))),
        }
        if white is not None:
            payload["white"] = max(0, min(255, int(white)))
        await self._request("POST", "led/color", json_data=payload)
        if switch_to_color_mode:
            await self.set_mode("color")

    # -------------------------------------------------------------------------
    # Group synchronization (Master / Slave)
    # -------------------------------------------------------------------------

    async def get_sync(self) -> SyncInfo:
        """Fetch group sync configuration from /xled/v1/sync (with software fallback for hwVersion 100)."""
        try:
            data = await self._request("GET", "sync")
            if data.get("code", 1000) != 1000:
                return self._software_sync
            self._probed_features["supports_sync_group"] = True
            self._software_sync = SyncInfo.from_dict(data)
            return self._software_sync
        except TwinklyConnectionError:
            return self._software_sync
        except TwinklyError:
            # Some Gen II revisions (e.g. TWS250SPP hwVersion 100 on FW 2.11.0) omit HTTP /xled/v1/sync;
            # keep supports_sync_group enabled and return software sync state.
            return self._software_sync

    async def set_sync(
        self,
        mode: str = "none",
        group_uid: str = "",
        master_uid: str = "",
        slave_id: int = 0,
        compat_mode: int = 0,
    ) -> None:
        """Configure device group synchronization role (none, master, slave)."""
        mode_clean = mode.lower()
        effective_group_uid = (
            (group_uid or uuid.uuid4().hex) if mode_clean == "master" else (group_uid if mode_clean == "slave" else "")
        )
        self._software_sync = SyncInfo(
            mode=mode_clean,
            group_uid=effective_group_uid,
            master_uid=master_uid if mode_clean == "slave" else "",
            slave_id=slave_id if mode_clean == "slave" else 0,
            compat_mode=compat_mode,
        )
        sync_payload: dict[str, Any] = {"mode": mode_clean}
        if mode_clean == "master":
            sync_payload["group_uid"] = effective_group_uid
            sync_payload["compat_mode"] = compat_mode
        elif mode_clean == "slave":
            sync_payload["group_uid"] = effective_group_uid
            if master_uid:
                sync_payload["master_uid"] = master_uid
            sync_payload["slave_id"] = slave_id
            sync_payload["compat_mode"] = compat_mode

        try:
            await self._request("POST", "sync", json_data={"sync": sync_payload})
        except TwinklyError:
            # Hardware without HTTP /xled/v1/sync still participates via TwinklyProCoordinator software routing
            pass

    # -------------------------------------------------------------------------
    # Spatial Layout (2D / 3D coordinates)
    # -------------------------------------------------------------------------

    async def get_layout(self, force_refresh: bool = False) -> DeviceLayout:
        """Fetch full 2D/3D spatial layout of LEDs from /xled/v1/led/layout/full."""
        if self._cached_layout is not None and not force_refresh:
            return self._cached_layout
        gestalt = await self.get_gestalt()
        try:
            data = await self._request("GET", "led/layout/full")
            self._cached_layout = DeviceLayout.from_dict(
                data, fallback_led_count=gestalt.number_of_led
            )
        except TwinklyError:
            self._cached_layout = DeviceLayout(
                source="3d",
                synthesized=True,
                coordinates=DeviceLayout.create_default_tree_coordinates(
                    gestalt.number_of_led
                ),
            )
        return self._cached_layout

    async def upload_layout(
        self,
        coordinates: list[LedCoordinate],
        source: str = "3d",
        synthesized: bool = False,
    ) -> None:
        """Upload custom 2D/3D spatial layout coordinates to the controller."""
        payload = {
            "source": source,
            "synthesized": synthesized,
            "uuid": str(uuid.uuid4()),
            "aspectXY": 0,
            "aspectXZ": 0,
            "coordinates": [c.to_dict() for c in coordinates],
        }
        await self._request("POST", "led/layout/full", json_data=payload)
        self._cached_layout = DeviceLayout.from_dict(payload)

    # -------------------------------------------------------------------------
    # Movies (Effects stored in flash memory)
    # -------------------------------------------------------------------------

    async def get_movies_state(self) -> MoviesState:
        """Fetch stored movies list and active movie."""
        try:
            movies_data = await self._request("GET", "movies")
            if movies_data.get("code", 1000) != 1000:
                self._probed_features["supports_multi_movies"] = False
                return MoviesState()
            self._probed_features["supports_multi_movies"] = True
        except TwinklyConnectionError:
            return MoviesState()
        except TwinklyError:
            self._probed_features["supports_multi_movies"] = False
            return MoviesState()

        current_data: dict[str, Any] | None = None
        try:
            current_data = await self._request("GET", "movies/current")
        except TwinklyError:
            pass

        return MoviesState.from_dict(movies_data, current_data)

    async def set_current_movie(self, movie_id: int, switch_mode: bool = True) -> None:
        """Select a movie by ID and optionally switch to movie mode."""
        await self._request("POST", "movies/current", json_data={"id": int(movie_id)})
        if switch_mode:
            await self.set_mode("movie")

    async def upload_movie(
        self,
        name: str,
        raw_frames: bytes,
        frames_number: int,
        fps: int = 20,
        leds_per_frame: int | None = None,
        descriptor_type: str | None = None,
        unique_id: str | None = None,
        activate: bool = True,
    ) -> int:
        """Upload a compiled binary movie into the controller's flash memory."""
        gestalt = await self.get_gestalt()
        if leds_per_frame is None:
            leds_per_frame = gestalt.number_of_led
        if descriptor_type is None:
            descriptor_type = (
                "rgbw_raw" if gestalt.led_profile == "RGBW" else "rgb_raw"
            )
        movie_uid = unique_id or str(uuid.uuid4())

        # Step 1: Register movie metadata
        meta_payload = {
            "name": name[:32],
            "unique_id": movie_uid,
            "descriptor_type": descriptor_type,
            "leds_per_frame": int(leds_per_frame),
            "frames_number": int(frames_number),
            "fps": int(fps),
        }
        try:
            meta_resp = await self._request(
                "POST", "movies/new", json_data=meta_payload
            )
            new_movie_id = int(meta_resp.get("id", 0))
            # Step 2: Upload raw binary buffer
            await self._request(
                "POST",
                "movies/full",
                raw_data=raw_frames,
                content_type="application/octet-stream",
            )
        except TwinklyError:
            # Fallback for older Generation I firmware
            await self._request(
                "POST",
                "led/movie/full",
                raw_data=raw_frames,
                content_type="application/octet-stream",
            )
            await self._request(
                "POST",
                "led/movie/config",
                json_data={
                    "frame_delay": int(1000 / max(1, fps)),
                    "leds_number": int(leds_per_frame),
                    "frames_number": int(frames_number),
                },
            )
            new_movie_id = 0

        if activate:
            try:
                await self.set_current_movie(new_movie_id, switch_mode=True)
            except TwinklyError:
                await self.set_mode("movie")

        return new_movie_id

    async def delete_all_movies(self) -> None:
        """Delete all movies from controller flash memory (frees up space)."""
        await self.turn_off()
        await self._request("DELETE", "movies")

    # -------------------------------------------------------------------------
    # Playlist management
    # -------------------------------------------------------------------------

    async def get_playlist_state(
        self, movies: list[MovieEntry] | None = None
    ) -> PlaylistState:
        """Fetch playlist entries and currently playing item."""
        try:
            playlist_data = await self._request("GET", "playlist")
            if playlist_data.get("code", 1000) != 1000:
                self._probed_features["supports_playlists"] = False
                return PlaylistState()
            self._probed_features["supports_playlists"] = True
        except TwinklyConnectionError:
            return PlaylistState()
        except TwinklyError:
            self._probed_features["supports_playlists"] = False
            return PlaylistState()

        current_data: dict[str, Any] | None = None
        try:
            current_data = await self._request("GET", "playlist/current")
        except TwinklyError:
            pass

        return PlaylistState.from_dict(playlist_data, current_data, movies=movies)

    async def set_playlist(
        self,
        entries: list[dict[str, Any]],
        activate: bool = True,
    ) -> None:
        """Write a new playlist to the controller.

        Each entry in `entries` should contain:
        `{"unique_id": "<movie_unique_id>", "duration": <seconds>}`
        """
        clean_entries = [
            {
                "unique_id": str(item["unique_id"]),
                "duration": max(1, int(item.get("duration", 30))),
            }
            for item in entries
            if item.get("unique_id")
        ]
        await self._request(
            "POST", "playlist", json_data={"entries": clean_entries}
        )
        if activate and clean_entries:
            await self.set_mode("playlist")

    async def delete_playlist(self) -> None:
        """Clear the playlist on the controller."""
        await self._request("DELETE", "playlist")

    async def set_current_playlist_item(self, item_id: int) -> None:
        """Jump to a specific playlist entry by index/ID."""
        await self._request(
            "POST", "playlist/current", json_data={"id": int(item_id)}
        )
        await self.set_mode("playlist")

    # -------------------------------------------------------------------------
    # Twinkly Music & reactive sound control
    # -------------------------------------------------------------------------

    async def get_music_state(self) -> MusicState:
        """Fetch Twinkly Music settings and available drivers."""
        enabled_data: dict[str, Any] | None = None
        drivers_data: dict[str, Any] | None = None
        current_driver_data: dict[str, Any] | None = None

        try:
            enabled_data = await self._request("GET", "music/enabled")
        except TwinklyError:
            pass

        try:
            drivers_data = await self._request("GET", "music/drivers")
            if drivers_data.get("code", 1000) == 1000:
                self._probed_features["supports_music_reactive"] = True
            else:
                self._probed_features["supports_music_reactive"] = False
        except TwinklyConnectionError:
            pass
        except TwinklyError:
            self._probed_features["supports_music_reactive"] = False

        try:
            current_driver_data = await self._request("GET", "music/drivers/current")
        except TwinklyError:
            pass

        return MusicState.from_dict(
            enabled_data=enabled_data,
            drivers_data=drivers_data,
            current_driver_data=current_driver_data,
        )

    async def set_music_enabled(self, enabled: bool = True) -> None:
        """Enable or disable music reactivity on the controller."""
        try:
            await self._request(
                "POST",
                "music/enabled",
                json_data={"enabled": 1 if enabled else 0},
            )
        except TwinklyError:
            pass
        if enabled:
            await self.set_mode("music")

    async def set_music_driver(
        self,
        driver_id: int | None = None,
        unique_id: str | None = None,
        activate_music_mode: bool = True,
    ) -> None:
        """Select a music driver / preset."""
        payload: dict[str, Any] = {}
        if unique_id:
            payload["unique_id"] = unique_id
        if driver_id is not None:
            payload["id"] = int(driver_id)
            payload["handle"] = int(driver_id)
        await self._request("POST", "music/drivers/current", json_data=payload)
        if activate_music_mode:
            await self.set_music_enabled(True)

    # -------------------------------------------------------------------------
    # Full device snapshot for DataUpdateCoordinator
    # -------------------------------------------------------------------------

    async def fetch_full_snapshot(
        self, include_layout: bool = False
    ) -> TwinklyDeviceSnapshot:
        """Gather a complete snapshot of the device state and compute DeviceCapabilities."""
        gestalt = await self.get_gestalt()
        fw_version = await self.get_firmware_version()

        if gestalt.is_music_dongle:
            music = await self.get_music_state()
            caps = DeviceCapabilities.from_gestalt(gestalt)
            return TwinklyDeviceSnapshot(
                host=self.host,
                gestalt=gestalt,
                fw_version=fw_version,
                mode="music" if (music.enabled or music.active) else "off",
                music=music,
                capabilities=caps,
                online=True,
            )

        mode_task = self.get_mode()
        brightness_task = self.get_brightness()
        color_task = self.get_color()
        sync_task = self.get_sync()
        movies_task = self.get_movies_state()
        music_task = self.get_music_state()

        (
            mode,
            brightness,
            color,
            sync,
            movies,
            music,
        ) = await asyncio.gather(
            mode_task,
            brightness_task,
            color_task,
            sync_task,
            movies_task,
            music_task,
        )

        playlist = await self.get_playlist_state(movies=movies.movies)
        layout = await self.get_layout(force_refresh=include_layout)
        caps = DeviceCapabilities.from_gestalt(gestalt, probed=self._probed_features)

        return TwinklyDeviceSnapshot(
            host=self.host,
            gestalt=gestalt,
            fw_version=fw_version,
            mode=mode,
            brightness=brightness,
            color=color,
            sync=sync,
            movies=movies,
            playlist=playlist,
            music=music,
            layout=layout,
            capabilities=caps,
            online=True,
        )
