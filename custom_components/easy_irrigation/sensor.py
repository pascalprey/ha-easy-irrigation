"""Sensor entities (bucket + duration) and entity services for Easy Irrigation."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)

from .const import DOMAIN
from .coordinator import EasyIrrigationCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the bucket and duration sensors for one zone."""
    coordinator: EasyIrrigationCoordinator = entry.runtime_data
    async_add_entities([BucketSensor(coordinator, entry), DurationSensor(coordinator, entry)])

    platform = async_get_current_platform()
    platform.async_register_entity_service("calculate", None, "async_service_calculate")
    platform.async_register_entity_service(
        "set_bucket", {vol.Required("value"): vol.Coerce(float)}, "async_service_set_bucket"
    )
    platform.async_register_entity_service("reset_bucket", None, "async_service_reset_bucket")


class _ZoneSensorBase(SensorEntity):
    """Shared base wiring an entity to the zone coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EasyIrrigationCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Easy Irrigation",
            model="Irrigation zone",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_listener(self.async_write_ha_state))

    # Entity services (delegated to the coordinator).
    async def async_service_calculate(self) -> None:
        await self._coordinator.async_calculate()

    async def async_service_set_bucket(self, value: float) -> None:
        await self._coordinator.async_set_bucket(value)

    async def async_service_reset_bucket(self) -> None:
        await self._coordinator.async_reset_bucket()


class BucketSensor(_ZoneSensorBase):
    """Current soil-moisture bucket in millimetres."""

    _attr_translation_key = "bucket"
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-outline"

    def __init__(self, coordinator: EasyIrrigationCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_bucket"

    @property
    def native_value(self) -> float:
        return round(self._coordinator.bucket, 2)


class DurationSensor(_ZoneSensorBase):
    """Recommended irrigation run time in seconds."""

    _attr_translation_key = "duration"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator: EasyIrrigationCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_duration"

    @property
    def native_value(self) -> int:
        return self._coordinator.duration
