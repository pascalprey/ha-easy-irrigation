"""Bucket bookkeeping and duration calculation for one irrigation zone."""

from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AREA,
    CONF_DRAINAGE,
    CONF_ET0_SENSOR,
    CONF_FLOW,
    CONF_LEAD_TIME,
    CONF_MAX_BUCKET,
    CONF_MAX_DURATION,
    CONF_MULTIPLIER,
    DOMAIN,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

_UNAVAILABLE = ("unknown", "unavailable", "none", "", None)


class EasyIrrigationCoordinator:
    """Holds the per-zone water balance and derives the irrigation duration.

    The bucket is depleted by the configured net ET0 (ET0 minus rainfall, in mm)
    exactly once per calendar day, so ``async_calculate`` can be called as often
    as desired during the day without double-counting evapotranspiration.
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

    def _read_et0(self) -> float | None:
        entity_id = self.config.get(CONF_ET0_SENSOR)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in _UNAVAILABLE:
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning("ET0 sensor %s is not numeric: %s", entity_id, state.state)
            return None

    def _recompute_duration(self) -> None:
        cfg = self.config
        if self.bucket < 0:
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
            self.bucket -= et0  # net ET0 already includes rainfall
            max_bucket = float(cfg[CONF_MAX_BUCKET])
            drainage = float(cfg.get(CONF_DRAINAGE, 0.0))
            if self.bucket > 0 and drainage > 0 and max_bucket > 0:
                self.bucket -= (
                    drainage * 24 * (min(self.bucket, max_bucket) / max_bucket) ** 4
                )
            self.bucket = min(self.bucket, max_bucket)
            self.last_et0_date = today
        elif et0 is None:
            _LOGGER.debug("No usable ET0 value for zone %s; duration only", self.entry.title)

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
