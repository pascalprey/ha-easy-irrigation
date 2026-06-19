"""Schedule controller: aggregates due zones into a watering plan.

It computes the total runtime, per-phase offsets and the start time (so watering
finishes ``sunrise_offset`` minutes before sunrise) plus a weather-based skip
flag. The minimum interval between waterings lives per zone (a zone within its
interval simply reports duration 0), so this controller only reads the current
zone durations.

It also drives the day on its own: a daily calculation at the configured
``calc_time`` depletes every zone's bucket and refreshes the plan, and -
optionally (``run_valves``) - the controller switches the valves itself at the
start time (phases sequentially, zones within a phase in parallel) and registers
each watering. With ``run_valves`` off it stays plan-only and the user's own
automation consumes these entities.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CALC_TIME,
    CONF_RAIN_THRESHOLD,
    CONF_RUN_VALVES,
    CONF_SUNRISE_OFFSET,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    DEFAULT_CALC_TIME,
    DEFAULT_RUN_VALVES,
    DEFAULTS,
    SIGNAL_SCHEDULE_UPDATED,
    phases_from_config,
    to_float,
)
from .schedule_math import compute_schedule

_LOGGER = logging.getLogger(__name__)

_UNAVAILABLE = ("unknown", "unavailable", "none", "", None)
_RECOMPUTE_INTERVAL = timedelta(seconds=60)

# Per valve domain: (service to open, service to close).
_VALVE_SERVICES = {
    "switch": ("turn_on", "turn_off"),
    "valve": ("open_valve", "close_valve"),
}


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
        # Per-zone next-watering info, keyed by zone entry_id (for the zone sensors).
        self.zone_next: dict[str, dict] = {}
        self._listeners: list[Callable[[], None]] = []
        self._unsub_timer: Callable[[], None] | None = None
        self._unsub_calc: Callable[[], None] | None = None
        self._start_unsub: Callable[[], None] | None = None
        self._pending_start: float | None = None
        self._running: bool = False
        self._run_task: asyncio.Task | None = None

    @property
    def config(self) -> dict:
        return {**self.entry.data, **self.entry.options}

    @property
    def run_valves(self) -> bool:
        """Whether this controller switches the valves itself."""
        return bool(self.config.get(CONF_RUN_VALVES, DEFAULT_RUN_VALVES))

    def start(self) -> None:
        self._unsub_timer = async_track_time_interval(
            self.hass, self._tick, _RECOMPUTE_INTERVAL
        )
        hour, minute, second = self._calc_time_parts()
        self._unsub_calc = async_track_time_change(
            self.hass, self._calc_fire, hour=hour, minute=minute, second=second
        )
        if self.run_valves:
            # The controller owns the valves in this mode: close them on load so a
            # restart that interrupted a run cannot leave a valve open.
            self.hass.async_create_task(self._async_safety_close())
        self.hass.async_create_task(self.async_recompute())

    def stop(self) -> None:
        for attr in ("_unsub_timer", "_unsub_calc", "_start_unsub"):
            unsub = getattr(self, attr, None)
            if unsub is not None:
                unsub()
                setattr(self, attr, None)
        self._pending_start = None
        if self._run_task is not None and not self._run_task.done():
            # Cancelling the run lets each zone's ``finally`` close its valve.
            self._run_task.cancel()

    def _calc_time_parts(self) -> tuple[int, int, int]:
        """Parse the configured ``HH:MM[:SS]`` calc time into integer parts."""
        raw = str(self.config.get(CONF_CALC_TIME) or DEFAULT_CALC_TIME)
        parts = raw.split(":")
        try:
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            second = int(parts[2]) if len(parts) > 2 else 0
        except (ValueError, IndexError):
            return 23, 0, 0
        return hour, minute, second

    @callback
    def _tick(self, _now) -> None:
        self.hass.async_create_task(self.async_recompute())

    @callback
    def _calc_fire(self, _now) -> None:
        self.hass.async_create_task(self._async_daily_calc())

    async def _async_daily_calc(self) -> None:
        """Deplete every zone's bucket (once/day) then refresh the plan."""
        for coordinator in self._zone_coordinators():
            try:
                await coordinator.async_calculate()
            except Exception as err:  # noqa: BLE001 - one bad zone must not stop the rest
                _LOGGER.warning(
                    "Easy Irrigation: daily calculate failed for a zone: %s", err
                )
        await self.async_recompute()

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()
        # Wake zone-owned "next watering" sensors, which live on a different
        # config entry and read this controller's plan via the dispatcher.
        async_dispatcher_send(self.hass, SIGNAL_SCHEDULE_UPDATED)

    def _phases(self) -> dict[int, list[str]]:
        """Configured phases -> {position (1-based): [zone duration-sensor ids]}."""
        phases_list = phases_from_config(self.config)
        return {i: list(zones) for i, zones in enumerate(phases_list, start=1) if zones}

    def _read_duration(self, sensor_id: str) -> float:
        state = self.hass.states.get(sensor_id)
        if state is None or state.state in _UNAVAILABLE:
            return 0.0
        value = to_float(state.state)
        return max(value, 0.0) if value is not None else 0.0

    def _valve_for(self, sensor_id: str) -> str | None:
        entity = er.async_get(self.hass).async_get(sensor_id)
        if entity is None or entity.config_entry_id is None:
            return None
        zone_entry = self.hass.config_entries.async_get_entry(entity.config_entry_id)
        if zone_entry is None:
            return None
        return {**zone_entry.data, **zone_entry.options}.get(CONF_VALVE_ENTITY)

    def _zone_entry_id_for(self, sensor_id: str) -> str | None:
        """Config entry_id of the zone owning a duration-sensor entity_id."""
        entity = er.async_get(self.hass).async_get(sensor_id)
        return entity.config_entry_id if entity is not None else None

    def _coordinator_for(self, sensor_id: str | None):
        """Return the zone coordinator owning a duration-sensor entity_id."""
        if not sensor_id:
            return None
        entity = er.async_get(self.hass).async_get(sensor_id)
        if entity is None or entity.config_entry_id is None:
            return None
        zone_entry = self.hass.config_entries.async_get_entry(entity.config_entry_id)
        coordinator = getattr(zone_entry, "runtime_data", None)
        # Duck-typed: a controller entry's runtime_data has no async_calculate.
        return coordinator if hasattr(coordinator, "async_calculate") else None

    def _zone_coordinators(self) -> list:
        """Unique zone coordinators referenced by this controller's phases."""
        result: list = []
        seen: set[int] = set()
        for sensors in self._phases().values():
            for sensor_id in sensors:
                coordinator = self._coordinator_for(sensor_id)
                if coordinator is not None and id(coordinator) not in seen:
                    seen.add(id(coordinator))
                    result.append(coordinator)
        return result

    async def _async_set_valve(self, valve: str, turn_on: bool) -> None:
        """Open or close a valve, honouring the switch vs valve domain."""
        domain = valve.split(".")[0]
        open_service, close_service = _VALVE_SERVICES.get(domain, ("turn_on", "turn_off"))
        await self.hass.services.async_call(
            domain,
            open_service if turn_on else close_service,
            {},
            target={"entity_id": valve},
            blocking=True,
        )

    async def _async_safety_close(self) -> None:
        """Close every configured valve (used on load in run_valves mode)."""
        for sensors in self._phases().values():
            for sensor_id in sensors:
                valve = self._valve_for(sensor_id)
                if not valve:
                    continue
                try:
                    await self._async_set_valve(valve, False)
                except Exception as err:  # noqa: BLE001 - best-effort safety
                    _LOGGER.debug("Safety close failed for %s: %s", valve, err)

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
        rain = to_float(forecast[0].get("precipitation")) or 0.0
        threshold = float(cfg.get(CONF_RAIN_THRESHOLD, DEFAULTS[CONF_RAIN_THRESHOLD]))
        return rain >= threshold

    async def async_recompute(self) -> None:
        """Rebuild the plan from the current zone durations and forecast."""
        cfg = self.config
        phases = self._phases()
        self.skip = await self._async_should_skip()

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
        self.zone_next = self._build_zone_next(phases)
        self._notify()
        self._reschedule_run()

    def _build_zone_next(self, phases: dict[int, list[str]]) -> dict[str, dict]:
        """Per-zone next-watering info keyed by zone entry_id.

        ``epoch`` is the zone's valve-open time (start + phase offset) when it is
        due and not rained off, else ``None`` with a ``status`` saying why
        (``not_due`` / ``rain_skip`` / ``no_schedule``).
        """
        result: dict[str, dict] = {}
        for index, sensors in phases.items():
            offset = int(self.stage_offsets.get(index, 0))
            for sensor_id in sensors:
                zone_entry_id = self._zone_entry_id_for(sensor_id)
                if not zone_entry_id:
                    continue
                duration = int(self._read_duration(sensor_id))
                if duration <= 0:
                    info = {"epoch": None, "status": "not_due", "duration": 0}
                elif self.skip:
                    info = {"epoch": None, "status": "rain_skip", "duration": duration}
                elif self.start_epoch is not None:
                    info = {
                        "epoch": self.start_epoch + offset,
                        "status": "scheduled",
                        "duration": duration,
                    }
                else:
                    info = {"epoch": None, "status": "no_schedule", "duration": duration}
                info["phase"] = index
                info["offset"] = offset
                result[zone_entry_id] = info
        return result

    # --- Built-in valve execution (run_valves mode) -----------------------

    def _reschedule_run(self) -> None:
        """Arm a one-shot timer at the start time when run_valves is enabled.

        Only arms for a *future* start time, which also prevents re-firing after a
        run finishes (the start time is then in the past until the next sunrise
        rolls the plan over to the following day).
        """
        if not self.run_valves or self._running:
            return
        target = self.start_epoch
        valid = (
            target is not None
            and self.total > 0
            and not self.skip
            and target > dt_util.utcnow().timestamp()
        )
        if not valid:
            self._cancel_run_timer()
            return
        if target == self._pending_start and self._start_unsub is not None:
            return
        self._cancel_run_timer()
        self._start_unsub = async_track_point_in_time(
            self.hass, self._start_fire, dt_util.utc_from_timestamp(target)
        )
        self._pending_start = target

    def _cancel_run_timer(self) -> None:
        if self._start_unsub is not None:
            self._start_unsub()
            self._start_unsub = None
        self._pending_start = None

    @callback
    def _start_fire(self, _now) -> None:
        self._start_unsub = None
        self._pending_start = None
        if self._running or self.skip or self.total <= 0:
            return
        self._run_task = self.hass.async_create_task(self._async_run_guarded())

    async def _async_run_guarded(
        self, *, test_seconds: int | None = None, register: bool = True
    ) -> None:
        """Execute the current plan once, closing valves whatever happens."""
        self._running = True
        try:
            await self._async_execute_plan(test_seconds=test_seconds, register=register)
        except asyncio.CancelledError:
            _LOGGER.warning("Easy Irrigation: watering run cancelled; valves closed")
            raise
        except Exception as err:  # noqa: BLE001 - log and recover
            _LOGGER.error("Easy Irrigation: watering run failed: %s", err)
        finally:
            self._running = False
            self._run_task = None

    async def async_run_now(
        self, *, ignore_skip: bool = True, test_seconds: int | None = None
    ) -> None:
        """Run the current plan now (manual / test trigger), in the background.

        Switches the valves regardless of ``run_valves``. With ``ignore_skip`` it
        also runs through an active rain skip; ``test_seconds`` overrides each due
        zone's duration for a short hardware/orchestration test and skips
        registering the watering (so the deficit is left untouched). Returns at
        once - the run continues as a tracked background task.
        """
        if self._running:
            _LOGGER.warning("Easy Irrigation: a watering run is already in progress")
            return
        if not ignore_skip and self.skip:
            _LOGGER.info("Easy Irrigation: manual run skipped (rain forecast)")
            return
        # Claim the run synchronously so two near-simultaneous triggers (e.g. the
        # service aimed at the whole controller device) cannot both start a run.
        self._running = True
        self._run_task = self.hass.async_create_task(
            self._async_run_guarded(
                test_seconds=test_seconds, register=test_seconds is None
            )
        )

    async def _async_execute_plan(
        self, *, test_seconds: int | None = None, register: bool = True
    ) -> None:
        """Run phases one after another; zones within a phase in parallel."""
        # Freeze the plan at start: the 60 s recompute keeps reassigning self.plan
        # (zones drop out as they register), but a run executes what was due at the
        # start time.
        plan = list(self.plan)
        for phase in plan:
            runs = [
                self._async_run_zone(zone, test_seconds=test_seconds, register=register)
                for zone in phase.get("zones", [])
                if zone.get("valve") and int(zone.get("duration", 0)) > 0
            ]
            if runs:
                await asyncio.gather(*runs)

    async def _async_run_zone(
        self, zone: dict, *, test_seconds: int | None = None, register: bool = True
    ) -> None:
        """Open a zone's valve for its duration, then register the watering."""
        valve = zone["valve"]
        duration = int(test_seconds) if test_seconds is not None else int(zone["duration"])
        await self._async_set_valve(valve, True)
        try:
            await asyncio.sleep(duration)
        except asyncio.CancelledError:
            # Fire-and-forget the close so a cancelled run still shuts the valve.
            self.hass.async_create_task(self._async_set_valve(valve, False))
            raise
        await self._async_set_valve(valve, False)
        if register:
            coordinator = self._coordinator_for(zone.get("duration_sensor"))
            if coordinator is not None:
                await coordinator.async_register_irrigation()
