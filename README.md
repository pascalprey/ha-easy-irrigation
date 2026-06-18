# Easy Irrigation (Home Assistant)

A lightweight, transparent soil-moisture **bucket** irrigation helper for Home Assistant.

It tracks a per-zone water balance (the "bucket") in millimetres: each day it subtracts the
net evapotranspiration (ET0 minus rainfall) and, once the bucket runs dry, computes how long
that zone needs to be watered. The actual valve switching stays in **your** automations - this
integration is the "brain" (buckets + durations), not the "hands".

> **Status:** early (v0.2). One zone = one config entry. See the roadmap below.

## Why

General-purpose irrigation integrations carry a lot of machinery (multiple weather backends,
sensor groups, calendars, custom frontends). This one is deliberately small: bring your own
ET0 (or let it compute ET0 from weather sensors), configure your zones, done.

## Installation (HACS custom repository)

1. HACS -> Integrations -> menu -> **Custom repositories** -> add this repository (category:
   *Integration*).
2. Install **Easy Irrigation**, then restart Home Assistant.
3. **Settings -> Devices & Services -> Add Integration -> Easy Irrigation**.

## Configuration

Add the integration **once per zone**. First pick the **ET0 source**:

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
weather sensors. Required: daily minimum & maximum temperature, mean wind speed, and either a
mean relative-humidity or a dew-point sensor. Optional: solar radiation (MJ/m^2/day; otherwise
estimated from the temperature range) and daily rainfall (to get net ET). Latitude and
elevation are taken from Home Assistant's configuration.

> Daily min/max/mean inputs are easiest to produce with native HA helpers (e.g. a
> `statistics` sensor with `value_max` / `value_min` / `mean` over 24 h). The integration does
> **not** buffer intraday samples itself - that keeps it simple and avoids a daily "clear".

### Zone parameters (both modes)

| Field | Meaning |
|---|---|
| Area (m^2) | Watered area of the zone. |
| Flow rate (L/min) | Combined output of the zone's emitters. |
| Maximum bucket (mm) | Cap for the water reserve. |
| Multiplier | Per-zone duration scaling (crop / efficiency factor). |
| Lead time (s) | Fixed time added to every run (valve-open delay, etc.). |
| Maximum duration (s) | Hard cap on a single run. |
| Drainage rate (mm/h) | Optional drainage of excess near saturation (`0` = off). |
| Min days between irrigations | Optional gate for the (future) scheduler. |

## How the maths works

Once per calendar day, per zone:

```
bucket = min(bucket - net_ET0, max_bucket)        # deplete by the day's net ET
```

On every `calculate` call the duration is recomputed from the current bucket:

```
if bucket < 0:
    precipitation_rate = flow_lpm * 60 / area_m2            # mm/h
    duration = |bucket| / precipitation_rate * 3600 * multiplier + lead_time
    duration = min(duration, max_duration)
else:
    duration = 0
```

ET0 is applied **only once per calendar day**, so you can call `calculate` as often as you
like during the day (e.g. after rain) without double-counting evapotranspiration.

## Entities (per zone)

- `sensor.<zone>_bucket` - current water balance (mm)
- `sensor.<zone>_duration` - recommended run time (s)

## Services

- `easy_irrigation.calculate` - recompute the targeted zone(s).
- `easy_irrigation.set_bucket` - set the bucket (mm).
- `easy_irrigation.reset_bucket` - reset the bucket to 0.

## Development

The FAO-56 maths lives in `custom_components/easy_irrigation/et0.py` and has no Home Assistant
dependencies, so it can be tested in isolation:

```bash
pytest tests/
```

## Schedule controller

Add a second config entry of type **schedule controller** to turn the per-zone durations into
a start plan. Each zone has a **stage** number: zones sharing a stage run in parallel, stages
run one after another. The controller therefore computes:

```
stage_runtime = max(durations of due zones in that stage)
total_runtime = sum of stage runtimes
start_time    = next_sunrise - sunrise_offset - total_runtime
```

It exposes (plan only - it does not switch valves):

- `sensor.<controller>_total_runtime` (s) - with `stage_durations` / `stage_offsets` attributes
- `sensor.<controller>_start_time` (timestamp) - when to start so watering finishes on time
- `binary_sensor.<controller>_skip` - on when the configured rain-forecast sensor is at or above
  the threshold (independent of the ET0 source)

Your own automation triggers at `start_time` (when not `skip`) and runs each stage's valves.

## Roadmap

- [x] In-house FAO-56 ET0 from local weather sensors (Mode B), using HA's configured location.
- [x] Multi-zone scheduler: finish at `sunrise - offset`; stages = parallel groups, total = sum.
- [x] Weather-based irrigation skip (rain forecast), independent of the ET0 source.
- [ ] `register_irrigation` service (post-watering bucket refill) + enforce minimum days between
      irrigations.
- [ ] Optional built-in valve execution.
- [ ] Number entities for live per-zone tuning.

## License

MIT - see [LICENSE](LICENSE).
