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
    MODE_OPENMETEO,
    MODE_SENSOR,
    STORAGE_VERSION,
    WIND_UNIT_KMH,
    to_float,
)
from .bucket_math import apply_net_et0
from .et0 import avp_from_dewpoint, avp_from_rh, et0_fao56, wind_speed_2m
from .openmeteo import async_get_openmeteo

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
        # How much net ET0 has already been booked for ``last_et0_date`` (lets a
        # re-calculation refresh to the latest value without double-counting).
        self.et0_applied: float | None = None
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
        self.et0_applied = data.get("et0_applied")
        self.last_irrigation_date = data.get("last_irrigation_date")
        self._recompute_duration()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "bucket": self.bucket,
                "last_et0_date": self.last_et0_date,
                "et0_applied": self.et0_applied,
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
        mode = cfg.get(CONF_MODE, MODE_SENSOR)
        if mode == MODE_CALCULATED:
            return self._compute_et0_from_weather(cfg)
        if mode == MODE_OPENMETEO:
            coordinator = async_get_openmeteo(self.hass)
            if coordinator is None:
                _LOGGER.warning(
                    "Easy Irrigation: zone %s uses Open-Meteo, but no Open-Meteo "
                    "source is configured - add one via Add Integration",
                    self.entry.title,
                )
                return None
            return coordinator.net
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
        """Apply today's net-ET0 depletion (refresh model) and recompute duration.

        The day's net ET0 is booked once and refreshed to the latest value on
        every later call of the same day (only the change is applied), so
        calculating repeatedly never double-counts yet always uses the newest
        value - both for the automatic daily run and the manual ``calculate``
        service. See :func:`bucket_math.apply_net_et0`.
        """
        cfg = self.config
        net = self._read_et0()
        today = dt_util.now().date().isoformat()
        self.bucket, self.last_et0_date, self.et0_applied = apply_net_et0(
            bucket=self.bucket,
            et0_date=self.last_et0_date,
            et0_applied=self.et0_applied,
            today=today,
            net=net,
            max_bucket=float(cfg[CONF_MAX_BUCKET]),
            drainage=float(cfg.get(CONF_DRAINAGE, 0.0)),
        )
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
