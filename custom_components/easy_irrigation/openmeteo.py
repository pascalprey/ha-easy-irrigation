"""Built-in Open-Meteo data source: one daily fetch of net ET0 + rainfall.

A single ``OpenMeteoCoordinator`` (one config entry) is shared by every zone
that picks the Open-Meteo ET0 source and by the schedule controller's rain skip,
so the API is queried once per location rather than once per consumer.

Open-Meteo's free API needs no key and is for **non-commercial** use; the data
is licensed CC BY 4.0 (see ``OPENMETEO_ATTRIBUTION``).
"""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ENTRY_TYPE_OPENMETEO,
    to_float,
)

_LOGGER = logging.getLogger(__name__)

_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class OpenMeteoCoordinator(DataUpdateCoordinator[dict]):
    """Fetches today's daily ET0 and rainfall for one location."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        cfg = {**entry.data, **entry.options}
        self.entry = entry
        self._lat = to_float(cfg.get(CONF_LATITUDE)) or hass.config.latitude
        self._lon = to_float(cfg.get(CONF_LONGITUDE)) or hass.config.longitude
        scan = int(to_float(cfg.get(CONF_SCAN_INTERVAL)) or DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name="Easy Irrigation Open-Meteo",
            update_interval=timedelta(seconds=max(scan, 300)),
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict:
        params = {
            "latitude": self._lat,
            "longitude": self._lon,
            "daily": "et0_fao_evapotranspiration,precipitation_sum",
            "timezone": self.hass.config.time_zone or "auto",
            "forecast_days": 1,
        }
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(_URL, params=params, timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Open-Meteo request failed: {err}") from err

        daily = payload.get("daily") or {}
        et0 = _first(daily.get("et0_fao_evapotranspiration"))
        rain = _first(daily.get("precipitation_sum"))
        date = _first(daily.get("time"))
        net = et0 - rain if et0 is not None and rain is not None else et0
        return {"et0": et0, "rain": rain, "net": net, "date": date}

    @property
    def net(self) -> float | None:
        """Daily net ET (ET0 minus rainfall) in mm."""
        return (self.data or {}).get("net")

    @property
    def et0(self) -> float | None:
        return (self.data or {}).get("et0")

    @property
    def rain(self) -> float | None:
        return (self.data or {}).get("rain")

    @property
    def forecast_date(self) -> str | None:
        return (self.data or {}).get("date")


def _first(values) -> float | None:
    if not values:
        return None
    return to_float(values[0])


def async_get_openmeteo(hass: HomeAssistant) -> OpenMeteoCoordinator | None:
    """Return the (single) configured Open-Meteo coordinator, if any.

    Most setups have exactly one Open-Meteo source; if several exist the first
    loaded one is used (a warning is logged once at read time by the caller).
    """
    store = hass.data.get(DOMAIN, {}).get(ENTRY_TYPE_OPENMETEO, {})
    for coordinator in store.values():
        return coordinator
    return None
