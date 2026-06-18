"""Schedule controller: aggregates due zones into a watering plan.

Plan-only: it computes the total runtime, per-phase offsets and the start time
(so watering finishes ``sunrise_offset`` minutes before sunrise), plus a
weather-based skip flag. It does not switch any valves - the user's automations
consume these entities. The plan exposes, per phase, each zone's valve entity.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_RAIN_THRESHOLD,
    CONF_SUNRISE_OFFSET,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    DEFAULTS,
    PHASE_COUNT,
    phase_key,
)
from .schedule_math import compute_schedule

_LOGGER = logging.getLogger(__name__)

_UNAVAILABLE = ("unknown", "unavailable", "none", "", None)
_RECOMPUTE_INTERVAL = timedelta(seconds=60)


class ScheduleController:
    """Aggregates the configured phases of zones into a single watering plan."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.total: float = 0.0
        self.start_epoch: float | None = None
        self.skip: bool = False
        self.stage_durations: dict[int, float] = {}
        self.stage_offsets: dict[int, float] = {}
        self.plan: list[dict] = []
        self._listeners: list[Callable[[], None]] = []
        self._unsub_timer: Callable[[], None] | None = None

    @property
    def config(self) -> dict:
        return {**self.entry.data, **self.entry.options}

    def start(self) -> None:
        self._unsub_timer = async_track_time_interval(
            self.hass, self._tick, _RECOMPUTE_INTERVAL
        )
        self.hass.async_create_task(self.async_recompute())

    def stop(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def _tick(self, _now) -> None:
        self.hass.async_create_task(self.async_recompute())

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    def _phases(self) -> dict[int, list[str]]:
        """Configured phases -> {phase_index: [zone duration-sensor entity_ids]}."""
        cfg = self.config
        phases: dict[int, list[str]] = {}
        for i in range(1, PHASE_COUNT + 1):
            zones = cfg.get(phase_key(i)) or []
            if zones:
                phases[i] = list(zones)
        return phases

    def _read_duration(self, sensor_id: str) -> float:
        state = self.hass.states.get(sensor_id)
        if state is None or state.state in _UNAVAILABLE:
            return 0.0
        try:
            return max(float(state.state), 0.0)
        except (ValueError, TypeError):
            return 0.0

    def _valve_for(self, sensor_id: str) -> str | None:
        entity = er.async_get(self.hass).async_get(sensor_id)
        if entity is None or entity.config_entry_id is None:
            return None
        zone_entry = self.hass.config_entries.async_get_entry(entity.config_entry_id)
        if zone_entry is None:
            return None
        return {**zone_entry.data, **zone_entry.options}.get(CONF_VALVE_ENTITY)

    def _next_sunrise_epoch(self) -> float | None:
        sun = self.hass.states.get("sun.sun")
        if sun is None:
            return None
        nxt = sun.attributes.get("next_rising")
        if not nxt:
            return None
        parsed = dt_util.parse_datetime(nxt)
        return parsed.timestamp() if parsed else None

    async def _async_should_skip(self) -> bool:
        cfg = self.config
        weather = cfg.get(CONF_WEATHER_ENTITY)
        if not weather:
            return False
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"type": "daily"},
                target={"entity_id": weather},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - forecast is best-effort
            _LOGGER.debug("Weather forecast unavailable for %s: %s", weather, err)
            return False
        forecast = ((response or {}).get(weather) or {}).get("forecast") or []
        if not forecast:
            return False
        rain = float(forecast[0].get("precipitation") or 0.0)
        threshold = float(cfg.get(CONF_RAIN_THRESHOLD, DEFAULTS[CONF_RAIN_THRESHOLD]))
        return rain >= threshold

    async def async_recompute(self) -> None:
        """Rebuild the plan from the current zone durations and forecast."""
        cfg = self.config
        phases = self._phases()

        stages: dict[int, list[float]] = {}
        for index, sensors in phases.items():
            durations = [d for d in (self._read_duration(s) for s in sensors) if d > 0]
            if durations:
                stages[index] = durations

        sunrise = self._next_sunrise_epoch()
        offset_min = float(cfg.get(CONF_SUNRISE_OFFSET, DEFAULTS[CONF_SUNRISE_OFFSET]))
        target = sunrise - offset_min * 60 if sunrise is not None else None

        result = compute_schedule(stages, target)
        self.total = result["total"]
        self.start_epoch = result["start_epoch"]
        self.stage_durations = result["stage_durations"]
        self.stage_offsets = result["stage_offsets"]

        plan: list[dict] = []
        for index in sorted(stages):
            zones: list[dict] = []
            for sensor_id in phases.get(index, []):
                duration = self._read_duration(sensor_id)
                if duration <= 0:
                    continue
                zones.append(
                    {
                        "duration_sensor": sensor_id,
                        "valve": self._valve_for(sensor_id),
                        "duration": int(duration),
                    }
                )
            if zones:
                plan.append(
                    {
                        "phase": index,
                        "offset": int(self.stage_offsets.get(index, 0)),
                        "duration": int(self.stage_durations.get(index, 0)),
                        "zones": zones,
                    }
                )
        self.plan = plan

        self.skip = await self._async_should_skip()
        self._notify()
