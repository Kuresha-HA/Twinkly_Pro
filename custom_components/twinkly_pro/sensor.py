"""Sensor entities for Twinkly Pro (Sync Group Role, Flash Memory, LED Layout)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
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
    """Set up Twinkly Pro sensor entities."""
    coordinator: TwinklyProCoordinator = hass.data[DOMAIN]["coordinators"][
        entry.entry_id
    ]
    async_add_entities(
        [
            TwinklyGroupRoleSensor(coordinator),
            TwinklyFlashMemorySensor(coordinator),
            TwinklyLedCountSensor(coordinator),
        ]
    )


class _TwinklyBaseSensor(CoordinatorEntity[TwinklyProCoordinator], SensorEntity):
    """Base sensor for Twinkly Pro."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: TwinklyProCoordinator, key: str, name: str, icon: str
    ) -> None:
        """Initialize base sensor."""
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


class TwinklyGroupRoleSensor(_TwinklyBaseSensor):
    """Sensor showing device synchronization role (Standalone, Master, Slave)."""

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize group role sensor."""
        super().__init__(
            coordinator, "sync_group_role", "Sync Group Role", "mdi:lan-connect"
        )

    @property
    def native_value(self) -> str:
        """Return human-readable group role."""
        snap = self.coordinator.data
        if not snap:
            return "Unknown"
        mode = snap.sync.mode
        if mode == "master":
            return "Master"
        if mode == "slave":
            return "Slave"
        return "Standalone"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return group details."""
        snap = self.coordinator.data
        if not snap:
            return {}
        target = self.coordinator.get_target_coordinator()
        return {
            "sync_mode": snap.sync.mode,
            "group_uid": snap.sync.group_uid,
            "master_uid": snap.sync.master_uid,
            "slave_id": snap.sync.slave_id,
            "routed_to_master_host": target.host if target is not self.coordinator else None,
        }


class TwinklyFlashMemorySensor(_TwinklyBaseSensor):
    """Sensor reporting used flash memory percentage and stored movie slots."""

    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize flash memory sensor."""
        super().__init__(
            coordinator, "flash_memory_used", "Flash Memory Used", "mdi:memory"
        )

    @property
    def native_value(self) -> float:
        """Return percentage of flash frame capacity used."""
        snap = self.coordinator.data
        if not snap or snap.movies.max_capacity <= 0:
            return 0.0
        used = max(0, snap.movies.max_capacity - snap.movies.available_frames)
        return round((used / float(snap.movies.max_capacity)) * 100.0, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed movie slot and frame counts."""
        snap = self.coordinator.data
        if not snap:
            return {}
        return {
            "stored_movies": len(snap.movies.movies),
            "max_movies": snap.movies.max_movies,
            "available_frames": snap.movies.available_frames,
            "max_capacity_frames": snap.movies.max_capacity,
            "movie_names": [m.name for m in snap.movies.movies],
        }


class TwinklyLedCountSensor(_TwinklyBaseSensor):
    """Sensor reporting total LED count and spatial mapping info."""

    _attr_native_unit_of_measurement = "LEDs"

    def __init__(self, coordinator: TwinklyProCoordinator) -> None:
        """Initialize LED count sensor."""
        super().__init__(
            coordinator, "led_count", "LED Count & Layout", "mdi:led-strip-variant"
        )

    @property
    def native_value(self) -> int:
        """Return total number of LEDs on the device."""
        snap = self.coordinator.data
        if not snap:
            return int(self.coordinator.entry.data.get("number_of_led", 0))
        return snap.gestalt.number_of_led

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return hardware and layout metadata."""
        snap = self.coordinator.data
        if not snap:
            return {}
        return {
            "led_profile": snap.gestalt.led_profile,
            "bytes_per_led": snap.gestalt.bytes_per_led,
            "product_code": snap.gestalt.product_code,
            "layout_source": snap.layout.source,
            "layout_synthesized": snap.layout.synthesized,
            "firmware_version": snap.fw_version,
            "host": snap.host,
            "mac": snap.gestalt.mac,
            "uuid": snap.gestalt.uuid,
        }
