"""The Twinkly Pro integration for Home Assistant."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
import uuid

from .const import (
    BUILTIN_EFFECT_PRESETS,
    CONF_DEVICES,
    CONF_HOST,
    CONF_MAC,
    DOMAIN,
    PANEL_ICON,
    PANEL_STATIC_PATH,
    PANEL_TITLE,
    PANEL_URL_PATH,
    SERVICE_CONFIGURE_SYNC_GROUP,
    SERVICE_SET_MODE,
    SERVICE_SET_PLAYLIST,
    SERVICE_START_RT_EFFECT,
    SERVICE_STOP_RT_EFFECT,
    SERVICE_UPLOAD_GENERATED_MOVIE,
)
from .twinkly_client import CURATED_GALLERY_TEMPLATES

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, ServiceCall
    from .coordinator import TwinklyProCoordinator
    from .twinkly_client import DeviceCapabilities

try:
    import voluptuous as vol
    from homeassistant.components import panel_custom, websocket_api
    from homeassistant.components.http import StaticPathConfig
    from homeassistant.const import Platform

    PLATFORMS: list[Platform] = [
        Platform.LIGHT,
        Platform.SELECT,
        Platform.NUMBER,
        Platform.BUTTON,
        Platform.SENSOR,
    ]
    _HAS_HA = True
except ImportError:
    # Allows standalone unit testing of custom_components.twinkly_pro.twinkly_client
    # without requiring the full Home Assistant core runtime installed.
    PLATFORMS = []
    _HAS_HA = False

_LOGGER = logging.getLogger(__name__)


def _async_cleanup_unsupported_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    caps: DeviceCapabilities,
    mac_prefix: str = "",
) -> None:
    """Remove entities from HA entity registry that are unsupported by DeviceCapabilities."""
    from homeassistant.helpers import entity_registry as er

    ent_reg = er.async_get(hass)
    is_music = caps.device_category == "music_dongle"

    supported_suffixes: set[str] = set()
    if caps.supports_light:
        supported_suffixes.update({"_light", "_operating_mode"})
    if caps.supports_multi_movies:
        supported_suffixes.add("_active_movie")
    if caps.supports_playlists:
        supported_suffixes.add("_playlist_track")
    if caps.supports_music_reactive:
        supported_suffixes.add("_music_driver")
    if caps.supports_rt_streaming:
        supported_suffixes.add("_live_rt_preset")

    if is_music:
        supported_suffixes.update(
            {
                "_mic_sensitivity",
                "_next_music_preset",
                "_prev_music_preset",
                "_music_dongle_status",
            }
        )
    else:
        if caps.supports_light and caps.supports_brightness:
            supported_suffixes.add("_brightness_pct")
        if caps.supports_playlists or caps.supports_multi_movies:
            supported_suffixes.update({"_next_effect", "_prev_effect"})
        if caps.supports_sync_group:
            supported_suffixes.update({"_leave_sync_group", "_sync_group_role"})
        if caps.supports_multi_movies:
            supported_suffixes.add("_flash_memory_used")
        if caps.supports_light:
            supported_suffixes.add("_led_count")
        if caps.is_matrix_tiles:
            supported_suffixes.add("_matrix_tiles")

    all_known_suffixes = (
        "_light",
        "_operating_mode",
        "_active_movie",
        "_playlist_track",
        "_music_driver",
        "_live_rt_preset",
        "_mic_sensitivity",
        "_brightness_pct",
        "_next_music_preset",
        "_prev_music_preset",
        "_next_effect",
        "_prev_effect",
        "_leave_sync_group",
        "_music_dongle_status",
        "_sync_group_role",
        "_flash_memory_used",
        "_led_count",
        "_matrix_tiles",
    )

    prefix_lower = f"{mac_prefix.lower()}_" if mac_prefix else ""
    for reg_entry in list(er.async_entries_for_config_entry(ent_reg, entry.entry_id)):
        uid = reg_entry.unique_id
        if prefix_lower and not uid.lower().startswith(prefix_lower):
            continue
        if any(uid.endswith(s) for s in all_known_suffixes) and not any(
            uid.endswith(s) for s in supported_suffixes
        ):
            ent_reg.async_remove(reg_entry.entity_id)


def _resolve_coordinator(
    hass: HomeAssistant, entry_id: str | None = None
) -> TwinklyProCoordinator | None:
    """Find a target TwinklyProCoordinator by coord_id/entry_id or return the first available."""
    domain_data = hass.data.get(DOMAIN, {})
    coordinators: dict[str, TwinklyProCoordinator] = domain_data.get(
        "coordinators", {}
    )
    if not coordinators:
        return None
    if entry_id:
        if entry_id in coordinators:
            return coordinators[entry_id]
        entry_list = domain_data.get("entry_coordinators", {}).get(entry_id)
        if entry_list:
            return entry_list[0]
    return next(iter(coordinators.values()))


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Twinkly Pro integration domain."""
    hass.data.setdefault(
        DOMAIN,
        {
            "coordinators": {},
            "entry_coordinators": {},
            "panel_registered": False,
            "ws_registered": False,
        },
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Twinkly Pro from a config entry (supports single or multi-device entries)."""
    from .coordinator import TwinklyProCoordinator

    hass.data.setdefault(
        DOMAIN,
        {
            "coordinators": {},
            "entry_coordinators": {},
            "panel_registered": False,
            "ws_registered": False,
        },
    )
    hass.data[DOMAIN].setdefault("entry_coordinators", {})

    raw_devices = entry.data.get(CONF_DEVICES)
    device_configs: list[dict[str, Any]]
    if isinstance(raw_devices, list) and raw_devices:
        device_configs = [dict(d) for d in raw_devices if isinstance(d, dict)]
    else:
        device_configs = [dict(entry.data)]

    entry_coords: list[TwinklyProCoordinator] = []
    for idx, dev_cfg in enumerate(device_configs):
        host = str(dev_cfg.get(CONF_HOST, ""))
        mac = str(dev_cfg.get(CONF_MAC, "")).lower()
        coord_id = mac or f"{entry.entry_id}_{idx}"
        coord = TwinklyProCoordinator(
            hass,
            entry,
            host=host,
            device_config=dev_cfg,
            coord_id=coord_id,
        )
        entry_coords.append(coord)

    await asyncio.gather(
        *(c.async_config_entry_first_refresh() for c in entry_coords)
    )

    hass.data[DOMAIN]["entry_coordinators"][entry.entry_id] = entry_coords
    for c in entry_coords:
        hass.data[DOMAIN]["coordinators"][c.coord_id] = c
        mac_prefix = (
            c.data.gestalt.mac
            if c.data and c.data.gestalt.mac
            else str(c.device_config.get(CONF_MAC, c.host))
        )
        _async_cleanup_unsupported_entities(
            hass, entry, c.capabilities, mac_prefix=mac_prefix
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services, WebSocket API, and Twinkly Studio web panel once
    _async_register_services(hass)
    _async_register_websocket_api(hass)
    await _async_register_studio_panel(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Twinkly Pro config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinators: dict[str, TwinklyProCoordinator] = hass.data[DOMAIN][
            "coordinators"
        ]
        entry_coords: list[TwinklyProCoordinator] = hass.data[DOMAIN].get(
            "entry_coordinators", {}
        ).pop(entry.entry_id, [])
        for c in entry_coords:
            coordinators.pop(c.coord_id, None)
            await c.async_shutdown()

    return unload_ok


# -----------------------------------------------------------------------------
# Custom Services
# -----------------------------------------------------------------------------


def _async_register_services(hass: HomeAssistant) -> None:
    """Register Twinkly Pro domain services."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_MODE):
        return

    async def handle_set_mode(call: ServiceCall) -> None:
        coord = _resolve_coordinator(hass, call.data.get("entry_id"))
        if coord:
            await coord.async_set_mode(str(call.data["mode"]))

    async def handle_upload_generated_movie(call: ServiceCall) -> None:
        coord = _resolve_coordinator(hass, call.data.get("entry_id"))
        if not coord:
            return
        params = {
            "primary_color": call.data.get("primary_color", "#ff007f"),
            "secondary_color": call.data.get("secondary_color", "#00e5ff"),
            "tertiary_color": call.data.get("tertiary_color", "#7c00ff"),
            "speed": float(call.data.get("speed", 1.0)),
            "scale": float(call.data.get("scale", 1.0)),
        }
        await coord.async_upload_generated_movie(
            name=str(call.data.get("name", "Studio Effect")),
            preset=str(call.data.get("preset", "rainbow_wave")),
            duration_seconds=float(call.data.get("duration_seconds", 6.0)),
            fps=int(call.data.get("fps", 20)),
            params=params,
            activate=True,
        )

    async def handle_set_playlist(call: ServiceCall) -> None:
        coord = _resolve_coordinator(hass, call.data.get("entry_id"))
        if not coord:
            return
        target = coord.get_target_coordinator()
        entries = list(call.data.get("entries", []))
        await target.client.set_playlist(entries, activate=True)
        await target.async_request_refresh()

    async def handle_start_rt_effect(call: ServiceCall) -> None:
        coord = _resolve_coordinator(hass, call.data.get("entry_id"))
        if not coord:
            return
        params = {
            "primary_color": call.data.get("primary_color", "#ff007f"),
            "secondary_color": call.data.get("secondary_color", "#00e5ff"),
            "speed": float(call.data.get("speed", 1.0)),
            "scale": float(call.data.get("scale", 1.0)),
        }
        await coord.async_start_rt_effect(
            preset=str(call.data.get("preset", "rainbow_wave")),
            fps=int(call.data.get("fps", 25)),
            params=params,
        )

    async def handle_stop_rt_effect(call: ServiceCall) -> None:
        coord = _resolve_coordinator(hass, call.data.get("entry_id"))
        if coord:
            await coord.async_stop_rt_effect()

    async def handle_configure_sync_group(call: ServiceCall) -> None:
        master_id = str(call.data["master_entry_id"])
        slave_ids = [str(x) for x in call.data.get("slave_entry_ids", [])]
        await _async_configure_group_internal(hass, master_id, slave_ids)

    hass.services.async_register(DOMAIN, SERVICE_SET_MODE, handle_set_mode)
    hass.services.async_register(
        DOMAIN, SERVICE_UPLOAD_GENERATED_MOVIE, handle_upload_generated_movie
    )
    hass.services.async_register(DOMAIN, SERVICE_SET_PLAYLIST, handle_set_playlist)
    hass.services.async_register(
        DOMAIN, SERVICE_START_RT_EFFECT, handle_start_rt_effect
    )
    hass.services.async_register(DOMAIN, SERVICE_STOP_RT_EFFECT, handle_stop_rt_effect)
    hass.services.async_register(
        DOMAIN, SERVICE_CONFIGURE_SYNC_GROUP, handle_configure_sync_group
    )


async def _async_configure_group_internal(
    hass: HomeAssistant,
    master_entry_id: str,
    slave_entry_ids: list[str],
) -> dict[str, Any]:
    """Configure Master/Slave group synchronization across selected controllers."""
    coordinators: dict[str, TwinklyProCoordinator] = hass.data[DOMAIN]["coordinators"]
    master_coord = coordinators.get(master_entry_id)
    if not master_coord:
        raise ValueError(f"Master entry_id '{master_entry_id}' not found")

    if not slave_entry_ids:
        # Disband group on master
        await master_coord.client.set_sync(mode="none")
        await master_coord.async_request_refresh()
        return {"group_uid": "", "mode": "none"}

    group_uid = uuid.uuid4().hex[:16]
    master_gestalt = await master_coord.client.get_gestalt()
    master_uuid = master_gestalt.uuid

    await master_coord.client.set_sync(mode="master", group_uid=group_uid)
    await master_coord.async_request_refresh()

    for idx, slave_entry_id in enumerate(slave_entry_ids, start=1):
        slave_coord = coordinators.get(slave_entry_id)
        if not slave_coord or slave_coord is master_coord:
            continue
        await slave_coord.client.set_sync(
            mode="slave",
            group_uid=group_uid,
            master_uid=master_uuid,
            slave_id=idx,
        )
        await slave_coord.async_request_refresh()

    return {"group_uid": group_uid, "mode": "master", "slaves": len(slave_entry_ids)}


# -----------------------------------------------------------------------------
# Embedded Twinkly Studio Panel & WebSocket API
# -----------------------------------------------------------------------------


async def _async_register_studio_panel(hass: HomeAssistant) -> None:
    """Register static frontend assets and the Twinkly Studio sidebar panel."""
    if hass.data[DOMAIN].get("panel_registered"):
        return

    frontend_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                PANEL_STATIC_PATH,
                str(frontend_dir),
                cache_headers=False,
            )
        ]
    )

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="twinkly-pro-panel",
        frontend_url_path=PANEL_URL_PATH,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=f"{PANEL_STATIC_PATH}/panel.js",
        embed_iframe=False,
        require_admin=False,
    )
    hass.data[DOMAIN]["panel_registered"] = True


def _serialize_coordinator(
    entry_id: str, coord: TwinklyProCoordinator
) -> dict[str, Any]:
    """Serialize a coordinator's full device snapshot for the Twinkly Studio web panel."""
    snap = coord.data
    if not snap:
        return {
            "entry_id": entry_id,
            "host": coord.host,
            "online": False,
        }
    target = coord.get_target_coordinator()
    return {
        "entry_id": entry_id,
        "host": snap.host,
        "online": snap.online,
        "is_music_dongle": coord.is_music_dongle,
        "name": snap.gestalt.device_name,
        "mac": snap.gestalt.mac,
        "uuid": snap.gestalt.uuid,
        "product_code": snap.gestalt.product_code,
        "fw_version": snap.fw_version,
        "number_of_led": snap.gestalt.number_of_led,
        "led_profile": snap.gestalt.led_profile,
        "bytes_per_led": snap.gestalt.bytes_per_led,
        "mode": snap.mode,
        "brightness": {
            "enabled": snap.brightness.enabled,
            "value": snap.brightness.value,
        },
        "color": {
            "red": snap.color.red,
            "green": snap.color.green,
            "blue": snap.color.blue,
            "white": snap.color.white,
        },
        "sync": {
            "mode": snap.sync.mode,
            "group_uid": snap.sync.group_uid,
            "master_uid": snap.sync.master_uid,
            "slave_id": snap.sync.slave_id,
            "routed_to_master_entry_id": (
                target.coord_id if target is not coord else None
            ),
        },
        "movies": {
            "available_frames": snap.movies.available_frames,
            "max_capacity": snap.movies.max_capacity,
            "max_movies": snap.movies.max_movies,
            "current_movie_id": snap.movies.current_movie_id,
            "items": [
                {
                    "id": m.id,
                    "name": m.name,
                    "unique_id": m.unique_id,
                    "frames_number": m.frames_number,
                    "fps": m.fps,
                }
                for m in snap.movies.movies
            ],
        },
        "playlist": {
            "current_id": snap.playlist.current_id,
            "current_unique_id": snap.playlist.current_unique_id,
            "entries": [
                {
                    "unique_id": e.unique_id,
                    "duration": e.duration,
                    "movie_id": e.movie_id,
                    "name": e.name,
                }
                for e in snap.playlist.entries
            ],
        },
        "music": {
            "enabled": snap.music.enabled,
            "active": snap.music.active,
            "current_driver_id": snap.music.current_driver_id,
            "drivers": [
                {"id": d.id, "unique_id": d.unique_id, "name": d.name}
                for d in snap.music.drivers
            ],
        },
        "layout": {
            "source": snap.layout.source,
            "synthesized": snap.layout.synthesized,
            "coordinates": [c.to_dict() for c in snap.layout.coordinates],
        },
        "is_rt_streaming": snap.is_rt_streaming,
        "active_rt_preset": snap.active_rt_preset,
    }


if _HAS_HA:

    def _async_register_websocket_api(hass: HomeAssistant) -> None:
        """Register WebSocket commands for the Twinkly Studio web panel."""
        if hass.data[DOMAIN].get("ws_registered"):
            return

        websocket_api.async_register_command(hass, ws_get_state)
        websocket_api.async_register_command(hass, ws_control_device)
        websocket_api.async_register_command(hass, ws_apply_effect)
        websocket_api.async_register_command(hass, ws_save_playlist)
        websocket_api.async_register_command(hass, ws_configure_group)
        hass.data[DOMAIN]["ws_registered"] = True

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "twinkly_pro/get_state",
        }
    )
    @websocket_api.async_response
    async def ws_get_state(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        """Return full state of all Twinkly Pro devices, presets, and gallery."""
        coordinators: dict[str, TwinklyProCoordinator] = hass.data.get(
            DOMAIN, {}
        ).get("coordinators", {})
        devices = [
            _serialize_coordinator(entry_id, coord)
            for entry_id, coord in coordinators.items()
        ]
        connection.send_result(
            msg["id"],
            {
                "devices": devices,
                "presets": BUILTIN_EFFECT_PRESETS,
                "gallery": CURATED_GALLERY_TEMPLATES,
            },
        )

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "twinkly_pro/control_device",
            vol.Required("entry_id"): str,
            vol.Required("action"): str,
            vol.Optional("payload", default={}): dict,
        }
    )
    @websocket_api.async_response
    async def ws_control_device(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        """Execute quick control actions from the Twinkly Studio web panel."""
        coord = _resolve_coordinator(hass, msg["entry_id"])
        if not coord:
            connection.send_error(msg["id"], "not_found", "Device not found")
            return

        action = msg["action"]
        payload = msg.get("payload", {})
        try:
            if action == "set_mode":
                await coord.async_set_mode(str(payload["mode"]))
            elif action == "set_brightness":
                await coord.async_set_brightness(int(payload["value"]))
            elif action == "set_color":
                await coord.async_set_color(
                    red=int(payload.get("red", 255)),
                    green=int(payload.get("green", 255)),
                    blue=int(payload.get("blue", 255)),
                    white=payload.get("white"),
                )
            elif action == "select_movie":
                await coord.async_select_movie(int(payload["movie_id"]))
            elif action == "select_playlist_item":
                await coord.async_select_playlist_item(int(payload["item_id"]))
            elif action == "select_music_driver":
                await coord.async_select_music_driver(
                    driver_id=int(payload["driver_id"]),
                    unique_id=str(payload.get("unique_id", "")),
                )
            elif action == "delete_all_movies":
                target = coord.get_target_coordinator()
                await target.client.delete_all_movies()
                await target.async_request_refresh()
            elif action == "refresh":
                await coord.async_request_refresh()
            else:
                connection.send_error(
                    msg["id"], "invalid_action", f"Unknown action: {action}"
                )
                return

            connection.send_result(
                msg["id"],
                {"device": _serialize_coordinator(coord.coord_id, coord)},
            )
        except Exception as err:
            _LOGGER.exception("Error in twinkly_pro/control_device")
            connection.send_error(msg["id"], "execution_error", str(err))

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "twinkly_pro/apply_effect",
            vol.Required("entry_id"): str,
            vol.Required("target_mode"): vol.In(["rt", "upload"]),
            vol.Required("preset"): str,
            vol.Optional("name", default="Studio Effect"): str,
            vol.Optional("fps", default=24): int,
            vol.Optional("duration", default=6.0): vol.Coerce(float),
            vol.Optional("params", default={}): dict,
        }
    )
    @websocket_api.async_response
    async def ws_apply_effect(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        """Start live UDP RT effect or compile & upload 2D/3D movie to device flash."""
        coord = _resolve_coordinator(hass, msg["entry_id"])
        if not coord:
            connection.send_error(msg["id"], "not_found", "Device not found")
            return

        try:
            if msg["target_mode"] == "rt":
                await coord.async_start_rt_effect(
                    preset=msg["preset"],
                    fps=int(msg["fps"]),
                    params=msg.get("params", {}),
                )
                movie_id = None
            else:
                movie_id = await coord.async_upload_generated_movie(
                    name=msg["name"],
                    preset=msg["preset"],
                    duration_seconds=float(msg["duration"]),
                    fps=int(msg["fps"]),
                    params=msg.get("params", {}),
                    activate=True,
                )

            connection.send_result(
                msg["id"],
                {
                    "movie_id": movie_id,
                    "device": _serialize_coordinator(coord.coord_id, coord),
                },
            )
        except Exception as err:
            _LOGGER.exception("Error in twinkly_pro/apply_effect")
            connection.send_error(msg["id"], "execution_error", str(err))

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "twinkly_pro/save_playlist",
            vol.Required("entry_id"): str,
            vol.Required("entries"): list,
            vol.Optional("activate", default=True): bool,
        }
    )
    @websocket_api.async_response
    async def ws_save_playlist(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        """Save edited playlist queue to the Twinkly controller."""
        coord = _resolve_coordinator(hass, msg["entry_id"])
        if not coord:
            connection.send_error(msg["id"], "not_found", "Device not found")
            return

        try:
            target = coord.get_target_coordinator()
            await target.client.set_playlist(
                entries=msg["entries"],
                activate=bool(msg.get("activate", True)),
            )
            await target.async_request_refresh()
            connection.send_result(
                msg["id"],
                {"device": _serialize_coordinator(target.coord_id, target)},
            )
        except Exception as err:
            _LOGGER.exception("Error in twinkly_pro/save_playlist")
            connection.send_error(msg["id"], "execution_error", str(err))

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "twinkly_pro/configure_group",
            vol.Required("master_entry_id"): str,
            vol.Optional("slave_entry_ids", default=[]): list,
        }
    )
    @websocket_api.async_response
    async def ws_configure_group(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        """Create or disband a Master/Slave synchronization group."""
        try:
            res = await _async_configure_group_internal(
                hass,
                master_entry_id=str(msg["master_entry_id"]),
                slave_entry_ids=[str(x) for x in msg.get("slave_entry_ids", [])],
            )
            coordinators: dict[str, TwinklyProCoordinator] = hass.data[DOMAIN][
                "coordinators"
            ]
            devices = [
                _serialize_coordinator(entry_id, coord)
                for entry_id, coord in coordinators.items()
            ]
            connection.send_result(msg["id"], {"group": res, "devices": devices})
        except Exception as err:
            _LOGGER.exception("Error in twinkly_pro/configure_group")
            connection.send_error(msg["id"], "execution_error", str(err))
