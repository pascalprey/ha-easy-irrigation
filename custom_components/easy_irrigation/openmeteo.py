"""Built-in Open-Meteo fetch: today's net ET0 (ET0 - rainfall) + rainfall.

A tiny module-level cache keyed by coordinates means many consumers (every
Open-Meteo zone at calculation time, plus the controller's rain skip) share one
HTTP request per location instead of each fetching their own.

Open-Meteo's free API needs no key and is for **non-commercial** use; the data
is licensed CC BY 4.0 (see ``OPENMETEO_ATTRIBUTION`` in const).
"""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import to_float

_LOGGER = logging.getLogger(__name__)

_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = aiohttp.ClientTimeout(total=30)
_CACHE_TTL = 1800  # seconds; one real request per location per ~30 min

# {(lat, lon): (fetched_at_epoch, data_dict)}
_CACHE: dict[tuple[float, float], tuple[float, dict]] = {}


def _first(values) -> float | None:
    if not values:
        return None
    return to_float(values[0])


async def async_fetch_openmeteo(
    hass: HomeAssistant, latitude: float, longitude: float
) -> dict | None:
    """Return today's ``{et0, rain, net, date}`` (mm) for a location, cached.

    On a network error the last cached value is returned if available, else
    ``None`` (callers treat ``None`` as "no data" - no depletion / no skip).
    """
    key = (round(float(latitude), 4), round(float(longitude), 4))
    now = dt_util.utcnow().timestamp()
    cached = _CACHE.get(key)
    if cached is not None and now - cached[0] < _CACHE_TTL:
        return cached[1]

    params = {
        "latitude": key[0],
        "longitude": key[1],
        "daily": "et0_fao_evapotranspiration,precipitation_sum",
        "timezone": hass.config.time_zone or "auto",
        "forecast_days": 1,
    }
    session = async_get_clientsession(hass)
    try:
        async with session.get(_URL, params=params, timeout=_TIMEOUT) as resp:
            resp.raise_for_status()
            payload = await resp.json()
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.warning("Open-Meteo request failed: %s", err)
        return cached[1] if cached is not None else None

    daily = payload.get("daily") or {}
    et0 = _first(daily.get("et0_fao_evapotranspiration"))
    rain = _first(daily.get("precipitation_sum"))
    date = _first_str(daily.get("time"))
    net = et0 - rain if et0 is not None and rain is not None else et0
    data = {"et0": et0, "rain": rain, "net": net, "date": date}
    _CACHE[key] = (now, data)
    return data


def _first_str(values) -> str | None:
    if not values:
        return None
    return str(values[0])
