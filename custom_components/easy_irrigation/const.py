"""Constants for the Easy Irrigation integration."""

from __future__ import annotations

DOMAIN = "easy_irrigation"
STORAGE_VERSION = 1

# Config keys
CONF_NAME = "name"
CONF_ET0_SENSOR = "et0_sensor"
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
}
