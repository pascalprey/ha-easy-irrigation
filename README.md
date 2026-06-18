# Easy Irrigation (Home Assistant)

A lightweight, transparent soil‑moisture **bucket** irrigation helper for Home Assistant.

It tracks a per‑zone water balance (the "bucket") in millimetres: each day it subtracts the
net evapotranspiration (ET0 minus rainfall) and, once the bucket runs dry, computes how long
that zone needs to be watered. The actual valve switching stays in **your** automations — this
integration is the "brain" (buckets + durations), not the "hands".

> **Status:** early scaffold (v0.1). One zone = one config entry. See the roadmap below.

## Why

General‑purpose irrigation integrations carry a lot of machinery (multiple weather backends,
sensor groups, calendars, custom frontends). This one is deliberately small: bring your own
daily ET0 number (from a weather API or a local weather station), configure your zones, done.

## Installation (HACS custom repository)

1. HACS → Integrations → ⋮ → **Custom repositories** → add this repository (category:
   *Integration*).
2. Install **Easy Irrigation**, then restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Easy Irrigation**.

## Configuration

Add the integration **once per zone**.

| Field | Meaning |
|---|---|
| ET0 sensor | A sensor giving the **daily net ET** in mm (ET0 − rainfall). |
| Area (m²) | Watered area of the zone. |
| Flow rate (L/min) | Combined output of the zone's emitters. |
| Maximum bucket (mm) | Cap for the water reserve. |
| Multiplier | Per‑zone duration scaling (crop / efficiency factor). |
| Lead time (s) | Fixed time added to every run (valve‑open delay, etc.). |
| Maximum duration (s) | Hard cap on a single run. |
| Drainage rate (mm/h) | Optional drainage of excess near saturation (`0` = off). |
| Min days between irrigations | Optional gate for the (future) scheduler. |

### Providing ET0

Any sensor returning a daily millimetre value works. A common free source is the
[Open‑Meteo](https://open-meteo.com/) `et0_fao_evapotranspiration` daily field, exposed via a
REST sensor. Replace `LAT` / `LON` with your coordinates; subtracting `precipitation_sum`
gives the **net** ET this integration expects:

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
like during the day (e.g. after rain) without double‑counting evapotranspiration.

## Entities (per zone)

- `sensor.<zone>_bucket` — current water balance (mm)
- `sensor.<zone>_duration` — recommended run time (s)

## Services

- `easy_irrigation.calculate` — recompute the targeted zone(s).
- `easy_irrigation.set_bucket` — set the bucket (mm).
- `easy_irrigation.reset_bucket` — reset the bucket to 0.

## Roadmap

- [ ] In‑house FAO‑56 ET0 from local weather sensors (temperature / humidity / wind / solar),
      using Home Assistant's configured location.
- [ ] Weather‑based irrigation skip (rain forecast), independent of the ET0 source.
- [ ] Multi‑zone scheduler: start so watering finishes at a target time; sequential (sum) or
      parallel (max) run groups.
- [ ] Enforce "minimum days between irrigations".
- [ ] Number entities for live per‑zone tuning.

## License

MIT — see [LICENSE](LICENSE).
