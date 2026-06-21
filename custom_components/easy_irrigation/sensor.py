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
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_CONTROLLER,
    ENTRY_TYPE_OPENMETEO,
    OPENMETEO_ATTRIBUTION,
    SIGNAL_SCHEDULE_UPDATED,
    phases_from_config,
)
from .controller import ScheduleController
from .coordinator import EasyIrrigationCoordinator
from .openmeteo import OpenMeteoCoordinator


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


def _remove_legacy_zone_next_sensors(
    hass: HomeAssistant, controller_entry: ConfigEntry
) -> None:
    """Drop the old controller-owned "next watering" sensors.

    Up to v0.6 these were created by the controller config entry, which made
    the controller span every zone device. They are now owned by each zone
    entry instead, so the stale controller-owned registry rows are removed.
    """
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, controller_entry.entry_id):
        if entity.unique_id.endswith("_next_watering"):
            registry.async_remove(entity.entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors for a zone, a schedule controller, or an Open-Meteo source."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_OPENMETEO:
        async_add_entities([NetEt0Sensor(entry.runtime_data, entry)])
        return

    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CONTROLLER:
        _remove_legacy_zone_next_sensors(hass, entry)
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

        # Controller-scoped service: run the current plan now (manual / test).
        async_get_current_platform().async_register_entity_service(
            "run_schedule",
            {
                vol.Optional("ignore_skip", default=True): cv.boolean,
                vol.Optional("test_seconds"): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=3600)
                ),
            },
            "async_service_run_schedule",
        )
        return

    coordinator: EasyIrrigationCoordinator = entry.runtime_data
    async_add_entities(
        [
            BucketSensor(coordinator, entry),
            DurationSensor(coordinator, entry),
            ZoneNextWateringSensor(entry),
        ]
    )

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

    async def async_service_run_schedule(
        self, ignore_skip: bool = True, test_seconds: int | None = None
    ) -> None:
        await self._controller.async_run_now(
            ignore_skip=ignore_skip, test_seconds=test_seconds
        )


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
        return {
            "stage_durations": {str(k): v for k, v in self._controller.stage_durations.items()},
            "stage_offsets": {str(k): v for k, v in self._controller.stage_offsets.items()},
            "skip": self._controller.skip,
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


class ZoneNextWateringSensor(SensorEntity):
    """When this zone is next due to be watered (lives on the zone's device).

    Owned by the zone config entry, so the zone device is not pulled into the
    schedule controller's entry. It reads its slot from whichever controller
    schedules this zone and refreshes on that controller's dispatcher signal.

    The value is the zone's valve-open time (controller start time + phase
    offset). It is ``unknown`` when the zone is not due, when rain skips the run,
    or when no start time can be computed - the ``status`` attribute says which,
    and ``skip`` mirrors the controller's rain-skip flag.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "next_watering"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"
    _attr_should_poll = False

    def __init__(self, zone_entry: ConfigEntry) -> None:
        self._zone_entry_id = zone_entry.entry_id
        self._attr_unique_id = f"{zone_entry.entry_id}_next_watering"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, zone_entry.entry_id)},
            name=zone_entry.title,
            manufacturer="Easy Irrigation",
            model="Irrigation zone",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SCHEDULE_UPDATED, self.async_write_ha_state
            )
        )

    def _resolve(self) -> tuple[ScheduleController | None, dict]:
        """Find the controller scheduling this zone and the zone's plan slot."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_CONTROLLER:
                continue
            controller = getattr(entry, "runtime_data", None)
            zone_next = getattr(controller, "zone_next", None)
            if zone_next and self._zone_entry_id in zone_next:
                return controller, zone_next[self._zone_entry_id]
        return None, {}

    @property
    def native_value(self) -> datetime | None:
        _, info = self._resolve()
        epoch = info.get("epoch")
        return dt_util.utc_from_timestamp(epoch) if epoch else None

    @property
    def extra_state_attributes(self) -> dict:
        controller, info = self._resolve()
        return {
            "status": info.get("status", "unknown"),
            "skip": bool(getattr(controller, "skip", False)),
            "phase": info.get("phase"),
            "offset_seconds": info.get("offset"),
            "duration_seconds": info.get("duration"),
        }


# --- Open-Meteo source sensor ---------------------------------------------


class NetEt0Sensor(CoordinatorEntity[OpenMeteoCoordinator], SensorEntity):
    """Daily net ET0 (ET0 minus rainfall) from the built-in Open-Meteo source.

    Shared by every zone that uses the Open-Meteo ET0 source; gross ET0 and
    rainfall are exposed as attributes. Diagnostic, so it stays out of the way.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "net_et0"
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-percent"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_attribution = OPENMETEO_ATTRIBUTION

    def __init__(self, coordinator: OpenMeteoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_net_et0"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Easy Irrigation",
            model="Open-Meteo source",
        )

    @property
    def native_value(self) -> float | None:
        net = self.coordinator.net
        return round(net, 2) if net is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "gross_et0_mm": self.coordinator.et0,
            "rainfall_mm": self.coordinator.rain,
            "forecast_date": self.coordinator.forecast_date,
        }
