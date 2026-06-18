"""Constants for the Easy Irrigation integration."""

from __future__ import annotations

DOMAIN = "easy_irrigation"
STORAGE_VERSION = 1

# ET0 source mode
CONF_MODE = "et0_mode"
MODE_SENSOR = "sensor"
MODE_CALCULATED = "calculated"

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
CONF_AREA = "area_m2"
CONF_FLOW = "flow_lpm"
CONF_MAX_BUCKET = "max_bucket_mm"
CONF_MAX_DURATION = "max_duration_s"
CONF_MULTIPLIER = "multiplier"
CONF_LEAD_TIME = "lead_time_s"
CONF_DRAINAGE = "drainage_rate"
CONF_DAYS_BETWEEN = "days_between"

# Defaults (neutral, must be adjusted per zone)
DEFAULTS: dict[str, float] = {
    CONF_AREA: 50.0,
    CONF_FLOW: 5.0,
    CONF_MAX_BUCKET: 20.0,
    CONF_MAX_DURATION: 3600.0,
    CONF_MULTIPLIER: 1.0,
    CONF_LEAD_TIME: 0.0,
    CONF_DRAINAGE: 0.0,
    CONF_DAYS_BETWEEN: 0.0,
    CONF_WIND_HEIGHT: 10.0,
}
