"""The Easy Irrigation integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_CONTROLLER
from .controller import ScheduleController
from .coordinator import EasyIrrigationCoordinator


def _is_controller(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CONTROLLER


def _platforms(entry: ConfigEntry) -> list[Platform]:
    if _is_controller(entry):
        return [Platform.SENSOR, Platform.BINARY_SENSOR]
    return [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a zone or a schedule controller from a config entry."""
    if _is_controller(entry):
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
