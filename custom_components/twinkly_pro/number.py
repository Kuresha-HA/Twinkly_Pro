"""Number entities for Twinkly Pro (Brightness percentage)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
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
    """Set up Twinkly Pro number entities."""
    coordinator: TwinklyProCoordinator = hass.data[DOMAIN]["coordinators"][
        entry.entry_id
    ]
    async_add_entities([TwinklyBrightnessNumber(coordinator)])


class TwinklyBrightnessNumber(
    CoordinatorEntity[TwinklyProCoordinator], NumberEntity
):
    """Master brightness slider (0-100%) for Twinkly controller."""

    _attr_has_entity_name = True
    _attr_name = "Master Brightness"
    _attr_icon = "mdi:brightness-percent"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize the brightness number entity."""
        super().__init__(coordinator)
        mac = (
            coordinator.data.gestalt.mac
            if coordinator.data
            else coordinator.entry.data.get("mac", coordinator.host)
        )
        self._attr_unique_id = f"{mac}_brightness_pct"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float | None:
        """Return the current brightness percentage."""
        snap = self.coordinator.data
        if not snap:
            return None
        return float(snap.brightness.value)

    async def async_set_native_value(self, value: float) -> None:
        """Set the master brightness percentage."""
        await self.coordinator.async_set_brightness(int(value))
