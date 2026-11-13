"""Twinkly Cloud account sync & curated effect gallery store client."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

import aiohttp

from .discovery import DiscoveredTwinklyDevice, async_discover_twinkly_devices

_LOGGER = logging.getLogger(__name__)

TWINKLY_CLOUD_ENDPOINTS: list[str] = [
    "https://api.twinkly.com/v2",
    "https://api.twinkly.com/v1",
]

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
    scenes: list[str] = field(default_factory=list)
    compositions: dict[str, str] = field(default_factory=dict)  # group_uid -> name


class TwinklyCloudClient:
    """Client for accessing Twinkly Cloud and merging cloud scenes/groups with LAN discovery."""

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        """Initialize the cloud client."""
        self._session = session
        self._owns_session = session is None
        self._token: str | None = None
        self._active_base: str = TWINKLY_CLOUD_ENDPOINTS[0]

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=8.0)
            )
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Close the HTTP session if owned by this client."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def login(self, email: str, password: str) -> bool:
        """Attempt login to Twinkly Cloud account."""
        if not email or not password:
            return False
        session = await self._ensure_session()

        for base_url in TWINKLY_CLOUD_ENDPOINTS:
            for path in ("/login", "/auth/login", "/users/login"):
                try:
                    async with session.post(
                        f"{base_url}{path}",
                        json={"email": email, "password": password},
                        headers={"Accept": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=6.0),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            if isinstance(data, dict):
                                token = (
                                    data.get("authorization_token")
                                    or data.get("authentication_token")
                                    or data.get("access_token")
                                    or data.get("token")
                                )
                                if token:
                                    self._token = str(token)
                                    self._active_base = base_url
                                    return True
                except Exception as err:
                    _LOGGER.debug(
                        "Twinkly cloud login probe %s%s failed: %s",
                        base_url,
                        path,
                        err,
                    )
        return False

    async def fetch_cloud_inventory(self) -> dict[str, Any]:
        """Fetch cloud devices, groups (compositions), and scenes if authenticated."""
        if not self._token:
            return {}
        session = await self._ensure_session()
        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Auth-Token": self._token,
            "Accept": "application/json",
        }
        inventory: dict[str, Any] = {"devices": [], "groups": [], "scenes": []}

        for key, path in (
            ("devices", "/devices"),
            ("groups", "/groups"),
            ("scenes", "/scenes"),
            ("scenes", "/installations"),
        ):
            try:
                async with session.get(
                    f"{self._active_base}{path}",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=6.0),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if isinstance(data, dict):
                            items = data.get(key) or data.get("data") or []
                            if isinstance(items, list):
                                inventory[key].extend(items)
                        elif isinstance(data, list):
                            inventory[key].extend(data)
            except Exception as err:
                _LOGGER.debug("Cloud inventory fetch %s skipped: %s", path, err)

        return inventory

    async def async_discover_account_and_lan(
        self,
        email: str = "",
        password: str = "",
        extra_hosts: list[str] | None = None,
    ) -> CloudAccountResult:
        """Authenticate with Cloud (if credentials given), scan LAN via UDP 5555, and merge."""
        session = await self._ensure_session()
        cloud_ok = False
        cloud_inv: dict[str, Any] = {}

        if email and password:
            cloud_ok = await self.login(email, password)
            if cloud_ok:
                cloud_inv = await self.fetch_cloud_inventory()

        # Always run fast UDP 5555 LAN broadcast discovery to locate live controllers & compositions
        lan_devices = await async_discover_twinkly_devices(
            session=session,
            extra_hosts=extra_hosts,
        )

        # Index cloud metadata by MAC / UUID
        cloud_by_mac: dict[str, dict[str, Any]] = {}
        cloud_by_uuid: dict[str, dict[str, Any]] = {}
        compositions: dict[str, str] = {}
        scenes_set: set[str] = set()

        for grp in cloud_inv.get("groups", []):
            if isinstance(grp, dict):
                gid = str(grp.get("uid") or grp.get("id") or grp.get("group_uid") or "")
                gname = str(grp.get("name") or "Композиция Twinkly")
                if gid:
                    compositions[gid] = gname

        for sc in cloud_inv.get("scenes", []):
            if isinstance(sc, dict) and sc.get("name"):
                scenes_set.add(str(sc["name"]))

        for cdev in cloud_inv.get("devices", []):
            if not isinstance(cdev, dict):
                continue
            cmac = str(cdev.get("mac") or cdev.get("hw_address") or "").lower()
            cuuid = str(cdev.get("uuid") or cdev.get("id") or "")
            if cmac:
                cloud_by_mac[cmac] = cdev
            if cuuid:
                cloud_by_uuid[cuuid] = cdev

        # Enrich LAN-discovered devices with Cloud scene & composition metadata
        for dev in lan_devices:
            c_meta = cloud_by_mac.get(dev.mac.lower()) or cloud_by_uuid.get(dev.uuid)
            if c_meta:
                dev.source = "cloud+lan"
                if c_meta.get("name"):
                    dev.name = str(c_meta["name"])
                scene_label = str(
                    c_meta.get("scene")
                    or c_meta.get("room")
                    or c_meta.get("installation_name")
                    or ""
                )
                if scene_label:
                    dev.scene_name = scene_label
                    scenes_set.add(scene_label)
                gid = str(c_meta.get("group_uid") or c_meta.get("group_id") or dev.group_uid)
                if gid:
                    dev.group_uid = gid

        # Also infer compositions directly from controller sync state (Master/Slave)
        master_names_by_group: dict[str, str] = {}
        for dev in lan_devices:
            if dev.sync_mode == "master" and dev.group_uid:
                master_names_by_group[dev.group_uid] = dev.name

        for dev in lan_devices:
            if dev.group_uid:
                comp_name = compositions.get(
                    dev.group_uid,
                    master_names_by_group.get(dev.group_uid, f"Группа {dev.group_uid[:6]}"),
                )
                dev.composition_name = comp_name
                compositions[dev.group_uid] = comp_name

        return CloudAccountResult(
            authenticated=cloud_ok,
            email=email,
            devices=lan_devices,
            scenes=sorted(scenes_set),
            compositions=compositions,
        )

    async def get_gallery_catalog(self) -> list[dict[str, Any]]:
        """Return curated effect gallery templates ready for 2D/3D compilation."""
        return list(CURATED_GALLERY_TEMPLATES)
