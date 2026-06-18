"""Schedule controller: aggregates due zones into a watering plan.

Plan-only: this computes the total runtime, the per-stage offsets and the start
time (so watering finishes ``sunrise_offset`` minutes before sunrise), plus a
weather-based skip flag. It does not switch any valves - the user's own
automations consume these entities.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ENTRY_TYPE,
    CONF_RAIN_FORECAST_SENSOR,
    CONF_RAIN_THRESHOLD,
    CONF_STAGE,
    CONF_SUNRISE_OFFSET,
    DEFAULTS,
    DOMAIN,
    ENTRY_TYPE_ZONE,
)
from .schedule_math import compute_schedule

_LOGGER = logging.getLogger(__name__)

_UNAVAILABLE = ("unknown", "unavailable", "none", "", None)
_RECOMPUTE_INTERVAL = timedelta(seconds=60)


class ScheduleController:
    """Aggregates the zone config entries into a single watering plan."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.total: float = 0.0
        self.start_epoch: float | None = None
        self.skip: bool = False
        self.stage_durations: dict[int, float] = {}
        self.stage_offsets: dict[int, float] = {}
        self._listeners: list[Callable[[], None]] = []
        self._unsub_timer: Callable[[], None] | None = None

    @property
    def config(self) -> dict:
        return {**self.entry.data, **self.entry.options}

    def start(self) -> None:
        """Begin periodic recomputation."""
        self._unsub_timer = async_track_time_interval(
            self.hass, self._tick, _RECOMPUTE_INTERVAL
        )
        self.recompute()

    def stop(self) -> None:
        """Stop periodic recomputation."""
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def _tick(self, _now) -> None:
        self.recompute()

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    def _zone_entries(self) -> list[ConfigEntry]:
        return [
            e
            for e in self.hass.config_entries.async_entries(DOMAIN)
            if e.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ZONE) == ENTRY_TYPE_ZONE
        ]

    def _next_sunrise_epoch(self) -> float | None:
        sun = self.hass.states.get("sun.sun")
        if sun is None:
            return None
        nxt = sun.attributes.get("next_rising")
        if not nxt:
            return None
        parsed = dt_util.parse_datetime(nxt)
        return parsed.timestamp() if parsed else None

    def _rain_forecast(self) -> float | None:
        entity_id = self.config.get(CONF_RAIN_FORECAST_SENSOR)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in _UNAVAILABLE:
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    @callback
    def recompute(self) -> None:
        """Rebuild the plan from the current zone durations."""
        cfg = self.config
        stages: dict[int, list[float]] = {}
        for zone_entry in self._zone_entries():
            coordinator = getattr(zone_entry, "runtime_data", None)
            duration = float(getattr(coordinator, "duration", 0) or 0) if coordinator else 0.0
            if duration <= 0:
                continue  # zone not due
            stage = int({**zone_entry.data, **zone_entry.options}.get(CONF_STAGE, 1))
            stages.setdefault(stage, []).append(duration)

        sunrise = self._next_sunrise_epoch()
        offset_min = float(cfg.get(CONF_SUNRISE_OFFSET, DEFAULTS[CONF_SUNRISE_OFFSET]))
        target = sunrise - offset_min * 60 if sunrise is not None else None

        result = compute_schedule(stages, target)
        self.total = result["total"]
        self.start_epoch = result["start_epoch"]
        self.stage_durations = result["stage_durations"]
        self.stage_offsets = result["stage_offsets"]

        rain = self._rain_forecast()
        threshold = float(cfg.get(CONF_RAIN_THRESHOLD, DEFAULTS[CONF_RAIN_THRESHOLD]))
        self.skip = rain is not None and rain >= threshold

        self._notify()
