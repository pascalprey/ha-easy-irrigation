"""Weather-based irrigation skip indicator for the schedule controller."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controller import ScheduleController


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the skip binary sensor for a schedule controller."""
    controller: ScheduleController = entry.runtime_data
    async_add_entities([SkipBinarySensor(controller, entry)])


class SkipBinarySensor(BinarySensorEntity):
    """On when the forecast rainfall is at or above the configured threshold."""

    _attr_has_entity_name = True
    _attr_translation_key = "skip"
    _attr_icon = "mdi:weather-rainy"

    def __init__(self, controller: ScheduleController, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_skip"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Easy Irrigation",
            model="Schedule controller",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.add_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        return self._controller.skip
