"""Sensor entities for Easy Irrigation: zone (bucket/duration) and controller."""

from __future__ import annotations

from datetime import datetime

import voluptuous as vol
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)
from homeassistant.util import dt as dt_util

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_CONTROLLER, phases_from_config
from .controller import ScheduleController
from .coordinator import EasyIrrigationCoordinator


def _zone_name(hass: HomeAssistant, sensor_id: str) -> str:
    """Human-readable zone name for a zone duration-sensor entity_id."""
    entity = er.async_get(hass).async_get(sensor_id)
    if entity is not None and entity.config_entry_id is not None:
        entry = hass.config_entries.async_get_entry(entity.config_entry_id)
        if entry is not None and entry.title:
            prefix = "Easy Irrigation "
            return entry.title[len(prefix):] if entry.title.startswith(prefix) else entry.title
    state = hass.states.get(sensor_id)
    if state is not None:
        return state.attributes.get("friendly_name", sensor_id)
    return sensor_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors for a zone or a schedule controller."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CONTROLLER:
        controller: ScheduleController = entry.runtime_data
        entities: list[SensorEntity] = [
            TotalRuntimeSensor(controller, entry),
            StartTimeSensor(controller, entry),
        ]
        phases = phases_from_config({**entry.data, **entry.options})
        for index, zone_sensors in enumerate(phases, start=1):
            names = [_zone_name(hass, s) for s in zone_sensors]
            label = f"Phase {index} ({', '.join(names)})" if names else f"Phase {index}"
            entities.append(PhaseDurationSensor(controller, entry, index, label))
        async_add_entities(entities)
        return

    coordinator: EasyIrrigationCoordinator = entry.runtime_data
    async_add_entities([BucketSensor(coordinator, entry), DurationSensor(coordinator, entry)])

    platform = async_get_current_platform()
    platform.async_register_entity_service("calculate", None, "async_service_calculate")
    platform.async_register_entity_service(
        "set_bucket", {vol.Required("value"): vol.Coerce(float)}, "async_service_set_bucket"
    )
    platform.async_register_entity_service("reset_bucket", None, "async_service_reset_bucket")
    platform.async_register_entity_service(
        "register_irrigation",
        {vol.Optional("amount_mm"): vol.Coerce(float)},
        "async_service_register_irrigation",
    )


# --- Zone sensors ---------------------------------------------------------


class _ZoneSensorBase(SensorEntity):
    """Shared base wiring a zone entity to its coordinator."""

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

    async def async_service_calculate(self) -> None:
        await self._coordinator.async_calculate()

    async def async_service_set_bucket(self, value: float) -> None:
        await self._coordinator.async_set_bucket(value)

    async def async_service_reset_bucket(self) -> None:
        await self._coordinator.async_reset_bucket()

    async def async_service_register_irrigation(self, amount_mm: float | None = None) -> None:
        await self._coordinator.async_register_irrigation(amount_mm)


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


# --- Controller sensors ---------------------------------------------------


class _ControllerSensorBase(SensorEntity):
    """Shared base wiring a controller entity to the schedule controller."""

    _attr_has_entity_name = True

    def __init__(self, controller: ScheduleController, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Easy Irrigation",
            model="Schedule controller",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.add_listener(self.async_write_ha_state))


class TotalRuntimeSensor(_ControllerSensorBase):
    """Total watering runtime across all due phases."""

    _attr_translation_key = "total_runtime"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-play-outline"

    def __init__(self, controller: ScheduleController, entry: ConfigEntry) -> None:
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_total_runtime"

    @property
    def native_value(self) -> int:
        return int(self._controller.total)

    @property
    def extra_state_attributes(self) -> dict:
        next_allowed = None
        if self._controller.next_allowed_epoch is not None:
            next_allowed = dt_util.utc_from_timestamp(
                self._controller.next_allowed_epoch
            ).isoformat()
        return {
            "stage_durations": {str(k): v for k, v in self._controller.stage_durations.items()},
            "stage_offsets": {str(k): v for k, v in self._controller.stage_offsets.items()},
            "skip": self._controller.skip,
            "blocked": self._controller.blocked,
            "next_allowed": next_allowed,
            "plan": self._controller.plan,
        }


class StartTimeSensor(_ControllerSensorBase):
    """When watering should start so it finishes at the target time."""

    _attr_translation_key = "start_time"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-start"

    def __init__(self, controller: ScheduleController, entry: ConfigEntry) -> None:
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_start_time"

    @property
    def native_value(self) -> datetime | None:
        epoch = self._controller.start_epoch
        if epoch is None or self._controller.total <= 0:
            return None
        return dt_util.utc_from_timestamp(epoch)


class PhaseDurationSensor(_ControllerSensorBase):
    """Runtime of one phase (longest due zone in that phase), in seconds."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self, controller: ScheduleController, entry: ConfigEntry, index: int, label: str
    ) -> None:
        super().__init__(controller, entry)
        self._index = index
        self._attr_name = label
        self._attr_unique_id = f"{entry.entry_id}_phase_{index}"

    @property
    def native_value(self) -> int:
        return int(self._controller.stage_durations.get(self._index, 0))
