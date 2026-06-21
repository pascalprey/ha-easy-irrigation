"""The Easy Irrigation integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_CONTROLLER,
    ENTRY_TYPE_OPENMETEO,
)
from .controller import ScheduleController
from .coordinator import EasyIrrigationCoordinator
from .openmeteo import OpenMeteoCoordinator


def _entry_type(entry: ConfigEntry) -> str:
    return entry.data.get(CONF_ENTRY_TYPE, "")


def _platforms(entry: ConfigEntry) -> list[Platform]:
    if _entry_type(entry) == ENTRY_TYPE_CONTROLLER:
        return [Platform.SENSOR, Platform.BINARY_SENSOR]
    return [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a zone, a schedule controller, or an Open-Meteo data source."""
    entry_type = _entry_type(entry)

    if entry_type == ENTRY_TYPE_OPENMETEO:
        coordinator = OpenMeteoCoordinator(hass, entry)
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        registry = hass.data.setdefault(DOMAIN, {}).setdefault(ENTRY_TYPE_OPENMETEO, {})
        registry[entry.entry_id] = coordinator
        entry.async_on_unload(lambda: registry.pop(entry.entry_id, None))
        await hass.config_entries.async_forward_entry_setups(entry, _platforms(entry))
    elif entry_type == ENTRY_TYPE_CONTROLLER:
        controller = ScheduleController(hass, entry)
        entry.runtime_data = controller
        await hass.config_entries.async_forward_entry_setups(entry, _platforms(entry))
        controller.start()
        entry.async_on_unload(controller.stop)
    else:
        coordinator = EasyIrrigationCoordinator(hass, entry)
        await coordinator.async_load()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, _platforms(entry))

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _platforms(entry))
