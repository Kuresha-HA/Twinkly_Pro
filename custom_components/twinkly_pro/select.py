"""Select entities for Twinkly Pro (Mode, Stored Movie, Playlist Track, Music Driver, Live RT)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ALL_MODES, BUILTIN_EFFECT_PRESETS, DOMAIN
from .coordinator import TwinklyProCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Twinkly Pro select entities based on device type (Garland vs Twinkly Music dongle)."""
    coordinator: TwinklyProCoordinator = hass.data[DOMAIN]["coordinators"][
        entry.entry_id
    ]
    if coordinator.is_music_dongle:
        async_add_entities([TwinklyMusicDriverSelect(coordinator)])
        return

    async_add_entities(
        [
            TwinklyModeSelect(coordinator),
            TwinklyMovieSelect(coordinator),
            TwinklyPlaylistTrackSelect(coordinator),
            TwinklyMusicDriverSelect(coordinator),
            TwinklyLivePresetSelect(coordinator),
        ]
    )


class _TwinklyBaseSelect(CoordinatorEntity[TwinklyProCoordinator], SelectEntity):
    """Base class for Twinkly Pro select entities."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: TwinklyProCoordinator, key: str, name: str, icon: str
    ) -> None:
        """Initialize the base select entity."""
        super().__init__(coordinator)
        mac = (
            coordinator.data.gestalt.mac
            if coordinator.data
            else coordinator.entry.data.get("mac", coordinator.host)
        )
        self._attr_unique_id = f"{mac}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = coordinator.device_info


class TwinklyModeSelect(_TwinklyBaseSelect):
    """Selector for Twinkly operating mode (off, color, movie, playlist, music, rt, demo)."""

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize the operating mode selector."""
        super().__init__(coordinator, "operating_mode", "Operating Mode", "mdi:tune-variant")
        self._attr_options = list(ALL_MODES)

    @property
    def current_option(self) -> str | None:
        """Return the current operating mode."""
        snap = self.coordinator.data
        if not snap:
            return None
        return snap.mode if snap.mode in ALL_MODES else "off"

    async def async_select_option(self, option: str) -> None:
        """Switch the Twinkly device to the selected operating mode."""
        await self.coordinator.async_set_mode(option)


class TwinklyMovieSelect(_TwinklyBaseSelect):
    """Selector for movies stored in the controller's flash memory."""

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize the stored movie selector."""
        super().__init__(coordinator, "active_movie", "Active Movie", "mdi:movie-open-star")

    @property
    def options(self) -> list[str]:
        """Return list of stored movies formatted as '<id>: <name>'."""
        snap = self.coordinator.data
        if not snap or not snap.movies.movies:
            return ["None"]
        return [f"{m.id}: {m.name}" for m in snap.movies.movies]

    @property
    def current_option(self) -> str | None:
        """Return currently selected movie."""
        snap = self.coordinator.data
        if not snap or not snap.movies.movies:
            return "None"
        curr_id = snap.movies.current_movie_id
        for m in snap.movies.movies:
            if m.id == curr_id:
                return f"{m.id}: {m.name}"
        first = snap.movies.movies[0]
        return f"{first.id}: {first.name}"

    async def async_select_option(self, option: str) -> None:
        """Activate the chosen movie."""
        if option == "None":
            return
        id_part = option.split(":", 1)[0].strip()
        if id_part.isdigit():
            await self.coordinator.async_select_movie(int(id_part))


class TwinklyPlaylistTrackSelect(_TwinklyBaseSelect):
    """Selector for tracks in the device playlist."""

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize the playlist track selector."""
        super().__init__(
            coordinator, "playlist_track", "Playlist Track", "mdi:playlist-music"
        )

    @property
    def options(self) -> list[str]:
        """Return playlist tracks formatted as '#<idx>: <name> (<duration>s)'."""
        snap = self.coordinator.data
        if not snap or not snap.playlist.entries:
            return ["Empty Playlist"]
        return [
            f"#{idx}: {entry.name} ({entry.duration}s)"
            for idx, entry in enumerate(snap.playlist.entries)
        ]

    @property
    def current_option(self) -> str | None:
        """Return currently active playlist track."""
        snap = self.coordinator.data
        if not snap or not snap.playlist.entries:
            return "Empty Playlist"
        curr_idx = snap.playlist.current_id or 0
        if 0 <= curr_idx < len(snap.playlist.entries):
            entry = snap.playlist.entries[curr_idx]
            return f"#{curr_idx}: {entry.name} ({entry.duration}s)"
        entry0 = snap.playlist.entries[0]
        return f"#0: {entry0.name} ({entry0.duration}s)"

    async def async_select_option(self, option: str) -> None:
        """Jump to the selected playlist item."""
        if not option.startswith("#"):
            return
        idx_str = option[1:].split(":", 1)[0].strip()
        if idx_str.isdigit():
            await self.coordinator.async_select_playlist_item(int(idx_str))


class TwinklyMusicDriverSelect(_TwinklyBaseSelect):
    """Selector for Twinkly Music reactive drivers / presets."""

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize the music driver selector."""
        super().__init__(coordinator, "music_driver", "Music Preset", "mdi:music-clef-treble")

    @property
    def options(self) -> list[str]:
        """Return available music drivers."""
        snap = self.coordinator.data
        if not snap or not snap.music.drivers:
            return ["Default Music Reactive"]
        return [f"{d.id}: {d.name}" for d in snap.music.drivers]

    @property
    def current_option(self) -> str | None:
        """Return currently selected music driver."""
        snap = self.coordinator.data
        if not snap or not snap.music.drivers:
            return "Default Music Reactive"
        curr_id = snap.music.current_driver_id
        for d in snap.music.drivers:
            if d.id == curr_id or (
                snap.music.current_driver_unique_id
                and d.unique_id == snap.music.current_driver_unique_id
            ):
                return f"{d.id}: {d.name}"
        first = snap.music.drivers[0]
        return f"{first.id}: {first.name}"

    async def async_select_option(self, option: str) -> None:
        """Activate the selected music driver."""
        if option == "Default Music Reactive":
            await self.coordinator.async_set_mode("music")
            return
        id_part = option.split(":", 1)[0].strip()
        if id_part.isdigit():
            driver_id = int(id_part)
            uid = ""
            if self.coordinator.data:
                for d in self.coordinator.data.music.drivers:
                    if d.id == driver_id:
                        uid = d.unique_id
                        break
            await self.coordinator.async_select_music_driver(driver_id, uid)


class TwinklyLivePresetSelect(_TwinklyBaseSelect):
    """Selector for procedural 2D/3D Live UDP Real-Time effects."""

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize the Live RT preset selector."""
        super().__init__(
            coordinator,
            "live_rt_preset",
            "Live 2D/3D Effect (UDP RT)",
            "mdi:creation",
        )
        self._attr_options = ["Stopped", *BUILTIN_EFFECT_PRESETS.values()]

    @property
    def current_option(self) -> str | None:
        """Return the active live RT preset."""
        snap = self.coordinator.data
        if not snap or not snap.is_rt_streaming or not snap.active_rt_preset:
            return "Stopped"
        return BUILTIN_EFFECT_PRESETS.get(snap.active_rt_preset, "Stopped")

    async def async_select_option(self, option: str) -> None:
        """Start or stop the live UDP RT effect stream."""
        if option == "Stopped":
            await self.coordinator.async_stop_rt_effect()
            return
        for key, label in BUILTIN_EFFECT_PRESETS.items():
            if label == option:
                await self.coordinator.async_start_rt_effect(preset=key)
                return
