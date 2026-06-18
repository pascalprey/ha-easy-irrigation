"""Bucket bookkeeping and duration calculation for one irrigation zone."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AREA,
    CONF_DEWPOINT_SENSOR,
    CONF_DRAINAGE,
    CONF_ET0_SENSOR,
    CONF_FLOW,
    CONF_HUMIDITY_SENSOR,
    CONF_LEAD_TIME,
    CONF_MAX_BUCKET,
    CONF_MAX_DURATION,
    CONF_MIN_DAYS_BETWEEN,
    CONF_MODE,
    CONF_MULTIPLIER,
    CONF_RAIN_SENSOR,
    CONF_SOLAR_SENSOR,
    CONF_TEMP_MAX_SENSOR,
    CONF_TEMP_MIN_SENSOR,
    CONF_WIND_HEIGHT,
    CONF_WIND_SENSOR,
    CONF_WIND_UNIT,
    DOMAIN,
    MODE_CALCULATED,
    MODE_SENSOR,
    STORAGE_VERSION,
    WIND_UNIT_KMH,
    to_float,
)
from .et0 import avp_from_dewpoint, avp_from_rh, et0_fao56, wind_speed_2m

_LOGGER = logging.getLogger(__name__)

_UNAVAILABLE = ("unknown", "unavailable", "none", "", None)


class EasyIrrigationCoordinator:
    """Holds the per-zone water balance and derives the irrigation duration.

    The bucket is depleted by the net ET0 (ET0 minus rainfall, in mm) exactly
    once per calendar day, so ``async_calculate`` can be called as often as
    desired during the day without double-counting evapotranspiration.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the coordinator for a config entry (one zone)."""
        self.hass = hass
        self.entry = entry
        self._store = Store[dict](hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.bucket: float = 0.0
        self.duration: int = 0
        self.last_et0_date: str | None = None
        self.last_irrigation_date: str | None = None
        self._listeners: list[Callable[[], None]] = []

    @property
    def config(self) -> dict:
        """Effective config: entry data overlaid with edited options."""
        return {**self.entry.data, **self.entry.options}

    async def async_load(self) -> None:
        """Restore persisted state and compute an initial duration."""
        data = await self._store.async_load() or {}
        self.bucket = float(data.get("bucket", 0.0))
        self.last_et0_date = data.get("last_et0_date")
        self.last_irrigation_date = data.get("last_irrigation_date")
        self._recompute_duration()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "bucket": self.bucket,
                "last_et0_date": self.last_et0_date,
                "last_irrigation_date": self.last_irrigation_date,
            }
        )

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        """Register an entity update callback; returns an unsubscribe callable."""
        self._listeners.append(cb)

        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    def _read_float(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in _UNAVAILABLE:
            return None
        value = to_float(state.state)
        if value is None:
            _LOGGER.warning("Sensor %s is not numeric: %s", entity_id, state.state)
        return value

    def _read_et0(self) -> float | None:
        """Return the daily net ET (mm) for this zone, by configured mode."""
        cfg = self.config
        if cfg.get(CONF_MODE, MODE_SENSOR) == MODE_CALCULATED:
            return self._compute_et0_from_weather(cfg)
        return self._read_float(cfg.get(CONF_ET0_SENSOR))

    def _compute_et0_from_weather(self, cfg: dict) -> float | None:
        """Compute net ET via FAO-56 from local daily weather sensors."""
        tmin = self._read_float(cfg.get(CONF_TEMP_MIN_SENSOR))
        tmax = self._read_float(cfg.get(CONF_TEMP_MAX_SENSOR))
        wind = self._read_float(cfg.get(CONF_WIND_SENSOR))
        if tmin is None or tmax is None or wind is None:
            _LOGGER.warning(
                "Easy Irrigation: missing temperature/wind input for zone %s",
                self.entry.title,
            )
            return None

        tdew = self._read_float(cfg.get(CONF_DEWPOINT_SENSOR))
        if tdew is not None:
            ea = avp_from_dewpoint(tdew)
        else:
            rh = self._read_float(cfg.get(CONF_HUMIDITY_SENSOR))
            if rh is None:
                _LOGGER.warning(
                    "Easy Irrigation: no humidity/dew-point input for zone %s",
                    self.entry.title,
                )
                return None
            ea = avp_from_rh(tmin, tmax, rh_mean=rh)

        if cfg.get(CONF_WIND_UNIT) == WIND_UNIT_KMH:
            wind = wind / 3.6
        u2 = wind_speed_2m(wind, float(cfg.get(CONF_WIND_HEIGHT, 10.0)))

        rs = self._read_float(cfg.get(CONF_SOLAR_SENSOR))  # optional, MJ/m²/day
        gross = et0_fao56(
            tmin=tmin,
            tmax=tmax,
            u2=u2,
            ea=ea if ea is not None else 0.0,
            elevation_m=float(self.hass.config.elevation or 0.0),
            lat_rad=math.radians(self.hass.config.latitude),
            doy=dt_util.now().timetuple().tm_yday,
            rs=rs,
        )

        rain = self._read_float(cfg.get(CONF_RAIN_SENSOR))
        return gross - rain if rain is not None else gross

    def _within_min_interval(self) -> bool:
        """True while the per-zone minimum interval since the last watering holds."""
        min_days = int(to_float(self.config.get(CONF_MIN_DAYS_BETWEEN, 0)) or 0)
        if min_days <= 0 or not self.last_irrigation_date:
            return False
        last = dt_util.parse_date(self.last_irrigation_date)
        if last is None:
            return False
        return (dt_util.now().date() - last).days < min_days

    def _recompute_duration(self) -> None:
        cfg = self.config
        if self.bucket < 0 and not self._within_min_interval():
            area = float(cfg[CONF_AREA])
            flow = float(cfg[CONF_FLOW])
            precipitation_rate = flow * 60 / area  # mm/h
            seconds = (
                abs(self.bucket) / precipitation_rate * 3600 * float(cfg[CONF_MULTIPLIER])
                + float(cfg[CONF_LEAD_TIME])
            )
            self.duration = int(min(seconds, float(cfg[CONF_MAX_DURATION])))
        else:
            self.duration = 0

    async def async_calculate(self) -> None:
        """Apply the daily ET0 depletion (once per day) and recompute duration."""
        cfg = self.config
        et0 = self._read_et0()
        today = dt_util.now().date().isoformat()

        if et0 is not None and self.last_et0_date != today:
            self.bucket -= et0  # net ET (rainfall already accounted for)
            max_bucket = float(cfg[CONF_MAX_BUCKET])
            drainage = float(cfg.get(CONF_DRAINAGE, 0.0))
            if self.bucket > 0 and drainage > 0 and max_bucket > 0:
                self.bucket -= (
                    drainage * 24 * (min(self.bucket, max_bucket) / max_bucket) ** 4
                )
            self.bucket = min(self.bucket, max_bucket)
            self.last_et0_date = today

        self._recompute_duration()
        await self._async_save()
        self._notify()

    async def async_set_bucket(self, value: float) -> None:
        """Force the bucket to a specific value (mm)."""
        self.bucket = float(value)
        self._recompute_duration()
        await self._async_save()
        self._notify()

    async def async_reset_bucket(self) -> None:
        """Reset the bucket to 0 mm."""
        await self.async_set_bucket(0.0)

    async def async_register_irrigation(self, amount: float | None = None) -> None:
        """Record that this zone was just watered.

        Refills the bucket (``amount`` mm if given, capped at the maximum;
        otherwise fully back to 0) and stamps today's date - the schedule
        controller uses the latest such date for the global minimum interval.
        """
        if amount is None:
            self.bucket = 0.0
        else:
            self.bucket = min(self.bucket + float(amount), float(self.config[CONF_MAX_BUCKET]))
        self.last_irrigation_date = dt_util.now().date().isoformat()
        self._recompute_duration()
        await self._async_save()
        self._notify()
