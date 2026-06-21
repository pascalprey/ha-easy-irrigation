"""Constants for the Easy Irrigation integration."""

from __future__ import annotations

DOMAIN = "easy_irrigation"
STORAGE_VERSION = 1

# Dispatcher signal fired whenever a schedule controller recomputes its plan.
# Zone "next watering" sensors listen for it to refresh from their controller.
SIGNAL_SCHEDULE_UPDATED = f"{DOMAIN}_schedule_updated"

# Entry type (a config entry is either a watering zone or a schedule controller)
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_ZONE = "zone"
ENTRY_TYPE_CONTROLLER = "controller"

# ET0 source mode (zone)
CONF_MODE = "et0_mode"
MODE_SENSOR = "sensor"
MODE_CALCULATED = "calculated"
MODE_OPENMETEO = "openmeteo"  # read net ET0 from the built-in Open-Meteo source

# Mode "sensor": a single sensor giving the daily *net* ET (ET0 - rainfall) in mm
CONF_ET0_SENSOR = "et0_sensor"

# Mode "calculated": FAO-56 from local weather sensors (daily-aggregated values)
CONF_TEMP_MIN_SENSOR = "temp_min_sensor"
CONF_TEMP_MAX_SENSOR = "temp_max_sensor"
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_DEWPOINT_SENSOR = "dewpoint_sensor"
CONF_WIND_SENSOR = "wind_sensor"
CONF_WIND_HEIGHT = "wind_height_m"
CONF_WIND_UNIT = "wind_unit"
CONF_SOLAR_SENSOR = "solar_sensor"
CONF_RAIN_SENSOR = "rain_sensor"

WIND_UNIT_MS = "ms"
WIND_UNIT_KMH = "kmh"

# Per-zone parameters
CONF_NAME = "name"
CONF_VALVE_ENTITY = "valve_entity"
CONF_AREA = "area_m2"
CONF_FLOW = "flow_lpm"
CONF_MAX_BUCKET = "max_bucket_mm"
CONF_MAX_DURATION = "max_duration_s"
CONF_MULTIPLIER = "multiplier"
CONF_LEAD_TIME = "lead_time_s"
CONF_DRAINAGE = "drainage_rate"
CONF_MIN_DAYS_BETWEEN = "min_days_between"

# Built-in Open-Meteo source: a per-zone ET0 mode (and optional rain skip) that
# fetches from Open-Meteo using the Home Assistant location. No separate entry.
OPENMETEO_ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"

# Schedule controller parameters
CONF_SUNRISE_OFFSET = "sunrise_offset_min"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_RAIN_THRESHOLD = "rain_threshold_mm"
CONF_CALC_TIME = "calc_time"      # daily wall-clock time to run the calculation (HH:MM:SS)
CONF_RUN_VALVES = "run_valves"    # let the controller switch the valves itself (no automation)
CONF_RAIN_SOURCE = "rain_source"  # where the rain-skip reads its forecast
RAIN_SOURCE_WEATHER = "weather"
RAIN_SOURCE_OPENMETEO = "openmeteo"
CONF_PHASES = "phases"  # list[list[zone duration-sensor entity_id]]

# Controller defaults that are not plain floats (kept out of DEFAULTS below)
DEFAULT_CALC_TIME = "23:00:00"
DEFAULT_RUN_VALVES = False
DEFAULT_RAIN_SOURCE = RAIN_SOURCE_WEATHER

# Flow-only keys (collected during the phase loop, never stored verbatim)
CONF_PHASE_ZONES = "zones"
CONF_ADD_ANOTHER = "add_another"

def to_float(value) -> float | None:
    """Parse a float, tolerant of comma decimals (e.g. ``"3,86"``).

    Returns ``None`` for non-numeric / missing input instead of raising, so a
    sensor that reports a localised value never crashes the calculation.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        pass
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


def phases_from_config(cfg: dict) -> list[list[str]]:
    """Return the controller's phases as a list of zone-sensor lists.

    Prefers the v0.4 ``phases`` list; falls back to the legacy v0.3.x
    ``phase_1`` / ``phase_2`` / ... keys so existing controllers keep working
    after an update (until the controller is edited and re-saved).
    """
    explicit = cfg.get(CONF_PHASES)
    if explicit is not None:
        return [list(phase) for phase in explicit]
    legacy: list[list[str]] = []
    for i in range(1, 13):
        zones = cfg.get(f"phase_{i}")
        if zones:
            legacy.append(list(zones))
    return legacy


# Defaults (neutral, must be adjusted per zone / controller)
DEFAULTS: dict[str, float] = {
    CONF_AREA: 50.0,
    CONF_FLOW: 5.0,
    CONF_MAX_BUCKET: 20.0,
    CONF_MAX_DURATION: 3600.0,
    CONF_MULTIPLIER: 1.0,
    CONF_LEAD_TIME: 0.0,
    CONF_DRAINAGE: 0.0,
    CONF_WIND_HEIGHT: 10.0,
    CONF_SUNRISE_OFFSET: 30.0,
    CONF_RAIN_THRESHOLD: 2.0,
    CONF_MIN_DAYS_BETWEEN: 0.0,
}
