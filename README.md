# Easy Irrigation (Home Assistant)

A lightweight, transparent soil-moisture **bucket** irrigation helper for Home Assistant.

It tracks a per-zone water balance (the "bucket") in millimetres: each day it subtracts the
net evapotranspiration (ET0 minus rainfall) and, once the bucket runs dry, computes how long
that zone needs to be watered. The actual valve switching stays in **your** automations - this
integration is the "brain" (buckets + durations + a start plan), not the "hands".

> **Status:** v0.4. One zone = one config entry; a schedule controller is a separate entry.

## Why

General-purpose irrigation integrations carry a lot of machinery (multiple weather backends,
sensor groups, calendars, custom frontends). This one is deliberately small: bring your own
ET0 (or let it compute ET0 from weather sensors), configure your zones, done.

## Installation (HACS custom repository)

1. HACS -> Integrations -> menu -> **Custom repositories** -> add this repository (category:
   *Integration*).
2. Install **Easy Irrigation**, then restart Home Assistant.
3. **Settings -> Devices & Services -> Add Integration -> Easy Irrigation**, then pick *zone*
   or *schedule controller*.

## Zones

Add a zone and pick the **ET0 source**.

### Mode A - From an ET0 sensor
Provide a sensor that returns the **daily net ET** (ET0 minus rainfall) in mm. A common free
source is the [Open-Meteo](https://open-meteo.com/) `et0_fao_evapotranspiration` daily field,
exposed via a REST sensor. Replace `LAT` / `LON` with your coordinates; subtracting
`precipitation_sum` gives the net ET this mode expects:

```yaml
rest:
  - resource: https://api.open-meteo.com/v1/forecast
    scan_interval: 1800
    params:
      latitude: "LAT"
      longitude: "LON"
      daily: et0_fao_evapotranspiration,precipitation_sum
      timezone: auto
      forecast_days: "1"
    sensor:
      - name: "Open-Meteo ET0 net"
        unique_id: openmeteo_et0_net
        unit_of_measurement: "mm"
        value_template: >-
          {{ (value_json.daily.et0_fao_evapotranspiration[0]
              - value_json.daily.precipitation_sum[0]) | round(2) }}
```

### Mode B - Computed from weather sensors (FAO-56)
Compute ET0 locally with the FAO-56 Penman-Monteith method from your own **daily-aggregated**
weather sensors (Tmin/Tmax, mean wind, and humidity or dew point; optional solar radiation and
rainfall). Latitude and elevation are taken from Home Assistant's configuration.

### Zone parameters (both modes)

| Field | Meaning |
|---|---|
| Valve | Optional `switch`/`valve` entity for the zone (used in the controller's plan). |
| Area (m^2) | Watered area of the zone. |
| Flow rate (L/min) | Combined output of the zone's emitters. |
| Maximum bucket (mm) | Cap for the water reserve. |
| Multiplier | Per-zone duration scaling (crop / efficiency factor). |
| Lead time (s) | Fixed time added to every run. |
| Maximum duration (s) | Hard cap on a single run. |
| Drainage rate (mm/h) | Optional drainage of excess near saturation (`0` = off). |

Each zone exposes `sensor.<zone>_bucket` (mm) and `sensor.<zone>_duration` (s), plus the
services `easy_irrigation.calculate`, `set_bucket`, `reset_bucket` and `register_irrigation`.

### Maths

Once per calendar day, per zone: `bucket = min(bucket - net_ET0, max_bucket)`. On every
`calculate` the duration is recomputed: when `bucket < 0`,
`duration = |bucket| / (flow_lpm*60/area_m2) * 3600 * multiplier + lead_time` (capped at
`max_duration`), else `0`. ET0 is applied **only once per calendar day**, so you can call
`calculate` as often as you like without double-counting.

## Schedule controller

Add a second entry of type **schedule controller**. After the controller settings you assign
zones to **phases** one at a time ("add another phase?") - so you create exactly as many phases
as you need, and zones already used are hidden from later phases. Phases run one after another;
zones within a phase run in parallel:

```
phase_runtime = max(durations of due zones in that phase)
total_runtime = sum of phase runtimes
start_time    = next_sunrise - sunrise_offset - total_runtime
```

It exposes (plan only - it does not switch valves):

- `sensor.<controller>_total_runtime` (s) - attributes: `stage_durations`, `stage_offsets`,
  `skip`, `blocked`, `next_allowed`, and a full `plan` (per phase: offset, duration, each
  zone's valve).
- `sensor.<controller>_phase_<n>` (s) - per-phase runtime, named `Phase n (zone, zone)`.
- `sensor.<controller>_start_time` (timestamp) - when to start.
- `binary_sensor.<controller>_skip` - on when the **weather entity**'s daily forecast rainfall
  is at or above the threshold.

### Minimum days between runs (shared pump)
The controller has a global **minimum interval**. After watering, your automation calls
`easy_irrigation.register_irrigation` on each watered zone (refills its bucket and stamps the
date). The controller takes the latest such date as the "last run"; until `min_days` have
passed it reports `blocked` and produces no plan (`total_runtime` 0, `start_time` empty,
`next_allowed` shows when it unblocks). This batches watering onto fewer nights - easier on a
groundwater pump.

Your automation triggers at `start_time` (when `skip` is off), reads the `plan` attribute and
opens each phase's valves for their durations, then calls `register_irrigation` per zone.

## Development

The FAO-56 maths (`et0.py`) and the scheduling maths (`schedule_math.py`) have no Home
Assistant dependencies and are unit-tested: `pytest tests/`.

## Roadmap

- [x] In-house FAO-56 ET0 from local weather sensors (Mode B).
- [x] Multi-zone scheduler: finish at `sunrise - offset`; phases = parallel groups.
- [x] On-demand phases (add as many as needed) with duplicate-zone exclusion + per-phase
      entities named `Phase n (zones)`.
- [x] Weather-based skip from a weather entity's rain forecast.
- [x] Per-zone valve entity, surfaced in the controller's plan.
- [x] `register_irrigation` service + global minimum days between runs.
- [ ] Optional built-in valve execution.
- [ ] Number entities for live per-zone tuning.

## License

MIT - see [LICENSE](LICENSE).
