"""Twinkly Cloud & curated effect gallery store client."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

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


class TwinklyCloudClient:
    """Client for accessing Twinkly Cloud and the curated effect store gallery."""

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        """Initialize the cloud client."""
        self._session = session
        self._token: str | None = None

    async def login(self, email: str, password: str) -> bool:
        """Attempt login to Twinkly Cloud account."""
        if not email or not password or self._session is None:
            return False
        try:
            async with self._session.post(
                f"{TWINKLY_CLOUD_BASE}/login",
                json={"email": email, "password": password},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    self._token = data.get("authorization_token") or data.get("token")
                    return bool(self._token)
        except Exception as err:
            _LOGGER.debug("Twinkly cloud login skipped or unavailable: %s", err)
        return False

    async def get_gallery_catalog(self) -> list[dict[str, Any]]:
        """Return curated effect gallery templates ready for 2D/3D compilation."""
        return list(CURATED_GALLERY_TEMPLATES)
