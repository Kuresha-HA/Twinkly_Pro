"""Twinkly Cloud account sync & curated effect gallery store client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any

import aiohttp

from .discovery import (
    DiscoveredTwinklyDevice,
    async_discover_twinkly_devices,
    async_probe_discovered_host,
)

_LOGGER = logging.getLogger(__name__)

TWINKLY_CLOUD_BASE = "https://api.twinkly.com/v2"

# Rich curated effect gallery templates available offline and online
CURATED_GALLERY_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "gallery_rainbow_spiral",
        "name": "Rainbow Spiral 3D",
        "category": "Classic",
        "preset": "rainbow_wave",
        "fps": 24,
        "duration": 6.0,
        "params": {
            "speed": 1.0,
            "scale": 1.2,
            "primary_color": "#ff0055",
            "secondary_color": "#00ffcc",
            "tertiary_color": "#ffcc00",
        },
        "description": "Плавная 3D радужная спираль по реальным координатам диодов",
    },
    {
        "id": "gallery_nordic_aurora",
        "name": "Nordic Aurora Borealis",
        "category": "Nature",
        "preset": "aurora_borealis",
        "fps": 20,
        "duration": 8.0,
        "params": {
            "speed": 0.8,
            "scale": 1.0,
            "primary_color": "#00ff88",
            "secondary_color": "#00b8ff",
            "tertiary_color": "#7b2cbf",
        },
        "description": "Северное сияние с изумрудными и фиолетовыми переливами",
    },
    {
        "id": "gallery_cozy_hearth",
        "name": "Cozy Christmas Fireplace",
        "category": "Warm & Cozy",
        "preset": "fire_flame",
        "fps": 25,
        "duration": 6.0,
        "params": {
            "speed": 1.1,
            "scale": 1.0,
            "primary_color": "#ff4500",
            "secondary_color": "#ffa500",
            "tertiary_color": "#ffd700",
        },
        "description": "Имитация живого пламени камина снизу вверх",
    },
    {
        "id": "gallery_diamond_snow",
        "name": "Diamond Starlight Sparkle",
        "category": "Holiday",
        "preset": "sparkle_twinkle",
        "fps": 24,
        "duration": 6.0,
        "params": {
            "speed": 1.0,
            "scale": 1.0,
            "primary_color": "#1e3a8a",
            "secondary_color": "#ffffff",
            "tertiary_color": "#93c5fd",
        },
        "description": "Глубокое сапфировое небо с яркими мерцающими искрами",
    },
    {
        "id": "gallery_gold_champagne",
        "name": "Warm Gold & Champagne",
        "category": "Holiday",
        "preset": "sparkle_twinkle",
        "fps": 20,
        "duration": 6.0,
        "params": {
            "speed": 0.75,
            "scale": 1.0,
            "primary_color": "#b45309",
            "secondary_color": "#fef08a",
            "tertiary_color": "#f59e0b",
        },
        "description": "Тёплое золотое свечение с деликатными вспышками шампанского",
    },
    {
        "id": "gallery_cyberpunk_plasma",
        "name": "Cyberpunk Neon Plasma",
        "category": "Modern",
        "preset": "plasma_2d",
        "fps": 25,
        "duration": 6.0,
        "params": {
            "speed": 1.2,
            "scale": 1.3,
            "primary_color": "#ff007f",
            "secondary_color": "#00f0ff",
            "tertiary_color": "#7000ff",
        },
        "description": "Неоновая интерференционная 2D/3D плазма в стиле киберпанк",
    },
    {
        "id": "gallery_sunset_horizon",
        "name": "Malibu Sunset Flow",
        "category": "Gradient",
        "preset": "gradient_flow",
        "fps": 20,
        "duration": 7.0,
        "params": {
            "speed": 0.85,
            "scale": 1.0,
            "primary_color": "#ff1e56",
            "secondary_color": "#ffac41",
            "tertiary_color": "#6a0572",
        },
        "description": "Мягкий перетекающий закатный градиент из трёх цветов",
    },
    {
        "id": "gallery_party_equalizer",
        "name": "Club Equalizer Spectrum",
        "category": "Music & Party",
        "preset": "equalizer_bars",
        "fps": 30,
        "duration": 5.0,
        "params": {
            "speed": 1.4,
            "scale": 1.0,
            "primary_color": "#00f5d4",
            "secondary_color": "#f15bb5",
            "tertiary_color": "#fee440",
        },
        "description": "Вертикальные столбики частотного анализатора с пиковыми точками",
    },
    {
        "id": "gallery_matrix_code",
        "name": "Digital Matrix Rain",
        "category": "Modern",
        "preset": "matrix_rain",
        "fps": 25,
        "duration": 6.0,
        "params": {
            "speed": 1.1,
            "scale": 1.0,
            "primary_color": "#00ff41",
            "secondary_color": "#008f11",
            "tertiary_color": "#ccffdd",
        },
        "description": "Падающие вертикальные капли цифрового дождя",
    },
]


@dataclass(slots=True)
class CloudAccountResult:
    """Result of cloud login and hybrid LAN + Cloud device/scene discovery."""

    authenticated: bool = False
    email: str = ""
    devices: list[DiscoveredTwinklyDevice] = field(default_factory=list)
    cloud_devices: list[DiscoveredTwinklyDevice] = field(default_factory=list)
    lan_only_devices: list[DiscoveredTwinklyDevice] = field(default_factory=list)
    scenes: list[str] = field(default_factory=list)
    compositions: dict[str, str] = field(default_factory=dict)  # group_uid -> name


def _normalize_mac(raw_mac: str) -> str:
    """Normalize MAC address to lowercase colon-separated aa:bb:cc:dd:ee:ff."""
    clean = (raw_mac or "").replace(":", "").replace("-", "").strip().lower()
    if len(clean) == 12:
        return ":".join(clean[i : i + 2] for i in range(0, 12, 2))
    return clean


def _extract_token(data: Any) -> str | None:
    """Extract bearer token from Twinkly Cloud /v2/auth response."""
    if not isinstance(data, dict):
        return None
    for key in (
        "access_token",
        "authorization_token",
        "authentication_token",
        "token",
        "id_token",
        "jwt",
    ):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    # Check nested 'data' or 'user' dict
    for nested_key in ("data", "result", "auth", "session"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            tok = _extract_token(nested)
            if tok:
                return tok
    return None


class TwinklyCloudClient:
    """Client for accessing Twinkly Cloud (/v2/auth, /v2/devices, /v2/objects) & LAN discovery."""

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        """Initialize the cloud client."""
        self._session = session
        self._owns_session = session is None
        self._token: str | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5.0)
            )
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Close the HTTP session if owned by this client."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def login(self, email: str, password: str) -> bool:
        """Authenticate against https://api.twinkly.com/v2/auth using username + password."""
        if not email or not password:
            return False
        session = await self._ensure_session()

        try:
            async with session.post(
                f"{TWINKLY_CLOUD_BASE}/auth",
                json={"username": email, "password": password},
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=3.5),
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json(content_type=None)
                    token = _extract_token(data)
                    if token:
                        self._token = token
                        return True
                else:
                    _LOGGER.debug(
                        "Twinkly Cloud /v2/auth returned HTTP %s", resp.status
                    )
        except Exception as err:
            _LOGGER.debug("Twinkly cloud /v2/auth error: %s", err)
        return False

    async def fetch_cloud_inventory(self) -> dict[str, Any]:
        """Fetch /v2/devices, /v2/objects, and /v2/users/me concurrently."""
        if not self._token:
            return {}
        session = await self._ensure_session()
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        inventory: dict[str, list[dict[str, Any]]] = {
            "devices": [],
            "objects": [],
            "profile": [],
        }

        async def _fetch_endpoint(bucket: str, path: str) -> None:
            try:
                async with session.get(
                    f"{TWINKLY_CLOUD_BASE}{path}",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=3.5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if isinstance(data, list):
                            inventory[bucket].extend(
                                [x for x in data if isinstance(x, dict)]
                            )
                        elif isinstance(data, dict):
                            # Could be {"devices": [...]} or {"objects": [...]} or {"data": [...]}
                            found_list = False
                            for k in (bucket, "data", "items", "devices", "objects"):
                                sub = data.get(k)
                                if isinstance(sub, list):
                                    inventory[bucket].extend(
                                        [x for x in sub if isinstance(x, dict)]
                                    )
                                    found_list = True
                            if not found_list:
                                inventory[bucket].append(data)
            except Exception as err:
                _LOGGER.debug("Cloud GET %s failed: %s", path, err)

        await asyncio.gather(
            _fetch_endpoint("devices", "/devices"),
            _fetch_endpoint("objects", "/objects"),
            _fetch_endpoint("profile", "/users/me"),
        )
        return inventory

    async def _async_cloud_flow(
        self, email: str, password: str
    ) -> tuple[bool, dict[str, Any]]:
        """Run cloud login + inventory fetch concurrently with LAN discovery."""
        if not email or not password:
            return False, {}
        ok = await self.login(email, password)
        if not ok:
            return False, {}
        inv = await self.fetch_cloud_inventory()
        return True, inv

    @staticmethod
    def _parse_cloud_records(
        cloud_inv: dict[str, Any],
    ) -> tuple[list[DiscoveredTwinklyDevice], dict[str, str], set[str]]:
        """Parse cloud /v2/devices and /v2/objects into DiscoveredTwinklyDevice list."""
        cloud_devices: list[DiscoveredTwinklyDevice] = []
        compositions: dict[str, str] = {}
        scenes_set: set[str] = set()

        # 1. Inspect /v2/objects (virtual objects, grouped compositions, scenes, installations)
        device_to_comp: dict[str, tuple[str, str, str]] = {}  # mac_or_uuid -> (group_uid, comp_name, scene_name)
        for obj in cloud_inv.get("objects", []):
            if not isinstance(obj, dict):
                continue
            obj_id = str(obj.get("id") or obj.get("uuid") or obj.get("uid") or "")
            obj_name = str(obj.get("name") or obj.get("title") or "")
            scene = str(
                obj.get("scene")
                or obj.get("room")
                or obj.get("environment")
                or obj.get("location")
                or ""
            )
            if scene:
                scenes_set.add(scene)

            sub_devs = (
                obj.get("devices")
                or obj.get("controllers")
                or obj.get("members")
                or obj.get("items")
                or []
            )
            if isinstance(sub_devs, list) and len(sub_devs) > 1 and obj_name:
                gid = obj_id or obj_name
                compositions[gid] = obj_name
                for sd in sub_devs:
                    if isinstance(sd, dict):
                        smac = _normalize_mac(
                            str(sd.get("mac") or sd.get("hw_address") or "")
                        )
                        suuid = str(sd.get("uuid") or sd.get("id") or "")
                        if smac:
                            device_to_comp[smac] = (gid, obj_name, scene)
                        if suuid:
                            device_to_comp[suuid] = (gid, obj_name, scene)
                    elif isinstance(sd, str):
                        device_to_comp[sd.lower()] = (gid, obj_name, scene)

            # Sometimes /v2/objects entries are the devices themselves
            if isinstance(sub_devs, list):
                for sd in sub_devs:
                    if isinstance(sd, dict):
                        cloud_inv.setdefault("devices", []).append(sd)
            elif obj.get("mac") or obj.get("product_code") or obj.get("hw_address"):
                cloud_inv.setdefault("devices", []).append(obj)

        # Also check profile for nested devices/objects
        for prof in cloud_inv.get("profile", []):
            if isinstance(prof, dict):
                for key in ("devices", "music_devices", "dongles", "objects"):
                    arr = prof.get(key)
                    if isinstance(arr, list):
                        for item in arr:
                            if isinstance(item, dict):
                                cloud_inv.setdefault("devices", []).append(item)

        # 2. Parse all physical devices (including Twinkly Music TMD01USB)
        seen_keys: set[str] = set()
        for cdev in cloud_inv.get("devices", []):
            if not isinstance(cdev, dict):
                continue
            if cdev.get("deleted") or cdev.get("is_deleted") or cdev.get("archived"):
                continue
            mac = _normalize_mac(
                str(
                    cdev.get("mac")
                    or cdev.get("hw_address")
                    or cdev.get("mac_address")
                    or ""
                )
            )
            uid = str(cdev.get("uuid") or cdev.get("id") or cdev.get("uid") or "")
            key = mac or uid.lower()
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)

            pcode = str(
                cdev.get("product_code")
                or cdev.get("model")
                or cdev.get("type")
                or cdev.get("device_type")
                or ""
            )
            is_music = (
                pcode.upper().startswith("TMD")
                or "music" in pcode.lower()
                or str(cdev.get("fw_family", "")).upper() == "M"
                or "music" in str(cdev.get("name", "")).lower()
            )
            if is_music and not pcode:
                pcode = "TMD01USB"

            name = str(
                cdev.get("name")
                or cdev.get("device_name")
                or ("Twinkly Music" if is_music else "Twinkly")
            )
            leds = int(
                cdev.get("number_of_led")
                or cdev.get("led_count")
                or cdev.get("leds")
                or 0
            )
            profile = str(
                cdev.get("led_profile") or ("MUSIC" if is_music else "RGB")
            ).upper()
            host_ip = str(
                cdev.get("ip")
                or cdev.get("local_ip")
                or cdev.get("ip_address")
                or cdev.get("host")
                or ""
            )
            scene = str(
                cdev.get("scene")
                or cdev.get("room")
                or cdev.get("installation_name")
                or ""
            )
            group_uid = str(cdev.get("group_uid") or cdev.get("group_id") or "")
            comp_name = str(cdev.get("group_name") or "")
            sync_mode = str(cdev.get("sync_mode") or cdev.get("role") or "none").lower()

            comp_info = device_to_comp.get(mac) or device_to_comp.get(uid)
            if comp_info:
                group_uid = group_uid or comp_info[0]
                comp_name = comp_name or comp_info[1]
                scene = scene or comp_info[2]

            if scene:
                scenes_set.add(scene)
            if group_uid and comp_name:
                compositions[group_uid] = comp_name

            cloud_devices.append(
                DiscoveredTwinklyDevice(
                    host=host_ip,
                    name=name,
                    mac=mac,
                    uuid=uid,
                    product_code=pcode,
                    number_of_led=leds,
                    led_profile=profile,
                    sync_mode=sync_mode,
                    group_uid=group_uid,
                    scene_name=scene,
                    composition_name=comp_name,
                    source="cloud",
                )
            )

        return cloud_devices, compositions, scenes_set

    async def async_discover_account_and_lan(
        self,
        email: str = "",
        password: str = "",
        extra_hosts: list[str] | None = None,
    ) -> CloudAccountResult:
        """Concurrently run Cloud sync (/v2/auth, /v2/devices, /v2/objects) and LAN UDP 5555 discovery."""
        session = await self._ensure_session()

        (cloud_ok, cloud_inv), lan_devices = await asyncio.gather(
            self._async_cloud_flow(email, password),
            async_discover_twinkly_devices(
                session=session,
                extra_hosts=extra_hosts,
                timeout=1.4,
            ),
        )

        cloud_devices, compositions, scenes_set = self._parse_cloud_records(cloud_inv)

        # Map LAN devices by MAC and UUID
        lan_by_mac: dict[str, DiscoveredTwinklyDevice] = {}
        lan_by_uuid: dict[str, DiscoveredTwinklyDevice] = {}
        for ldev in lan_devices:
            if ldev.mac:
                lan_by_mac[_normalize_mac(ldev.mac)] = ldev
            if ldev.uuid:
                lan_by_uuid[ldev.uuid] = ldev

        final_cloud_devices: list[DiscoveredTwinklyDevice] = []
        matched_lan_ids: set[str] = set()

        for cdev in cloud_devices:
            matched_lan = (
                lan_by_mac.get(_normalize_mac(cdev.mac))
                if cdev.mac
                else None
            ) or (lan_by_uuid.get(cdev.uuid) if cdev.uuid else None)

            if matched_lan:
                matched_lan_ids.add(matched_lan.unique_id)
                matched_lan.source = "cloud+lan"
                if cdev.name and matched_lan.name in ("Twinkly", ""):
                    matched_lan.name = cdev.name
                if cdev.scene_name:
                    matched_lan.scene_name = cdev.scene_name
                if cdev.composition_name:
                    matched_lan.composition_name = cdev.composition_name
                if cdev.group_uid and not matched_lan.group_uid:
                    matched_lan.group_uid = cdev.group_uid
                final_cloud_devices.append(matched_lan)
            else:
                # Cloud device is offline or didn't respond to UDP broadcast
                if cdev.host:
                    probed = await async_probe_discovered_host(
                        cdev.host, session=session, fallback_name=cdev.name
                    )
                    if probed:
                        probed.source = "cloud+lan"
                        probed.scene_name = cdev.scene_name
                        probed.composition_name = cdev.composition_name
                        matched_lan_ids.add(probed.unique_id)
                        final_cloud_devices.append(probed)
                        continue
                    # Stale IP in cloud and device didn't respond -> mark offline
                    cdev.host = ""
                final_cloud_devices.append(cdev)

        lan_only_devices = [
            ldev for ldev in lan_devices if ldev.unique_id not in matched_lan_ids
        ]
        merged_devices = final_cloud_devices + lan_only_devices

        # Also infer compositions from controller Master/Slave sync state on LAN
        master_names_by_group: dict[str, str] = {}
        for dev in merged_devices:
            if dev.sync_mode == "master" and dev.group_uid:
                master_names_by_group[dev.group_uid] = dev.name

        for dev in merged_devices:
            if dev.group_uid:
                comp_name = compositions.get(
                    dev.group_uid,
                    master_names_by_group.get(
                        dev.group_uid, f"Группа {dev.group_uid[:6]}"
                    ),
                )
                dev.composition_name = comp_name
                compositions[dev.group_uid] = comp_name

        return CloudAccountResult(
            authenticated=cloud_ok,
            email=email,
            devices=merged_devices,
            cloud_devices=final_cloud_devices,
            lan_only_devices=lan_only_devices,
            scenes=sorted(scenes_set),
            compositions=compositions,
        )

    async def get_gallery_catalog(self) -> list[dict[str, Any]]:
        """Return curated effect gallery templates ready for 2D/3D compilation."""
        return list(CURATED_GALLERY_TEMPLATES)
