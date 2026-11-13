"""Button entities for Twinkly Pro (separate buttons for LED Garlands vs Twinkly Music)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TwinklyProCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Twinkly Pro button entities depending on device type."""
    coordinator: TwinklyProCoordinator = hass.data[DOMAIN]["coordinators"][
        entry.entry_id
    ]
    if coordinator.is_music_dongle:
        async_add_entities(
            [
                TwinklyNextMusicPresetButton(coordinator),
                TwinklyPrevMusicPresetButton(coordinator),
            ]
        )
        return

    async_add_entities(
        [
            TwinklyNextTrackButton(coordinator),
            TwinklyPrevTrackButton(coordinator),
            TwinklyLeaveGroupButton(coordinator),
        ]
    )


class _TwinklyBaseButton(CoordinatorEntity[TwinklyProCoordinator], ButtonEntity):
    """Base button entity for Twinkly Pro."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: TwinklyProCoordinator, key: str, name: str, icon: str
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        mac = (
            coordinator.data.gestalt.mac
            if coordinator.data and coordinator.data.gestalt.mac
            else coordinator.entry.data.get("mac", coordinator.host)
        )
        self._attr_unique_id = f"{mac}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = coordinator.device_info


class TwinklyNextTrackButton(_TwinklyBaseButton):
    """Button to advance to the next playlist entry or stored movie on a garland."""

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize Next Track button."""
        super().__init__(
            coordinator, "next_effect", "Next Effect / Playlist Track", "mdi:skip-next"
        )

    async def async_press(self) -> None:
        """Advance to the next effect."""
        await self.coordinator.async_step_playlist_or_movie(step=1)


class TwinklyPrevTrackButton(_TwinklyBaseButton):
    """Button to return to the previous playlist entry or stored movie on a garland."""

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize Previous Track button."""
        super().__init__(
            coordinator,
            "prev_effect",
            "Previous Effect / Playlist Track",
            "mdi:skip-previous",
        )

    async def async_press(self) -> None:
        """Step back to the previous effect."""
        await self.coordinator.async_step_playlist_or_movie(step=-1)


class TwinklyLeaveGroupButton(_TwinklyBaseButton):
    """Button to remove a garland controller from any Master/Slave sync group."""

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize Leave Sync Group button."""
        super().__init__(
            coordinator,
            "leave_sync_group",
            "Leave Sync Group (Standalone)",
            "mdi:link-off",
        )

    async def async_press(self) -> None:
        """Set sync mode to none."""
        if self.coordinator.host:
            await self.coordinator.client.set_sync(mode="none")
            await self.coordinator.async_request_refresh()


class TwinklyNextMusicPresetButton(_TwinklyBaseButton):
    """Button to switch to the next audio-reactive preset on a Twinkly Music dongle."""

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize Next Music Preset button."""
        super().__init__(
            coordinator, "next_music_preset", "Next Music Preset", "mdi:skip-next"
        )

    async def async_press(self) -> None:
        """Advance to the next music driver."""
        await self.coordinator.async_step_music_driver(step=1)


class TwinklyPrevMusicPresetButton(_TwinklyBaseButton):
    """Button to switch to the previous audio-reactive preset on a Twinkly Music dongle."""

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize Previous Music Preset button."""
        super().__init__(
            coordinator,
            "prev_music_preset",
            "Previous Music Preset",
            "mdi:skip-previous",
        )

    async def async_press(self) -> None:
        """Return to the previous music driver."""
        await self.coordinator.async_step_music_driver(step=-1)
