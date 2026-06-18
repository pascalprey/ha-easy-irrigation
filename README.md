# Easy Irrigation (Home Assistant)

A lightweight, transparent soil-moisture **bucket** irrigation helper for Home Assistant.

It tracks a per-zone water balance (the "bucket") in millimetres: each day it subtracts the
net evapotranspiration (ET0 minus rainfall) and, once the bucket runs dry, computes how long
that zone needs to be watered. The actual valve switching stays in **your** automations - this
integration is the "brain" (buckets + durations + a start plan), not the "hands".

> **Status:** v0.5. One zone = one config entry; a schedule controller is a separate entry.
> The UI is available in English and German (chosen by your Home Assistant language).

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

Add a zone and pick the **ET0 source** (a daily-net ET0 sensor, or FAO-56 computed from your
own daily-aggregated weather sensors).

### Zone parameters

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
| Min days between irrigations | The zone reports duration `0` until this many days have passed since it was last watered (deep, infrequent watering). `0` = off. |

Each zone exposes `sensor.<zone>_bucket` (mm) and `sensor.<zone>_duration` (s), plus the
services `easy_irrigation.calculate`, `set_bucket`, `reset_bucket` and `register_irrigation`.

### Maths

Once per calendar day, per zone: `bucket = min(bucket - net_ET0, max_bucket)`. On every
`calculate` the duration is recomputed: when `bucket < 0` **and** the zone's minimum interval
has elapsed, `duration = |bucket| / (flow_lpm*60/area_m2) * 3600 * multiplier + lead_time`
(capped at `max_duration`), else `0`. ET0 is applied **only once per calendar day**.

> All sensor values are parsed comma-tolerantly (`"3,86"` works as well as `"3.86"`), so a
> localised sensor never breaks the calculation.

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
  `skip`, and a full `plan` (per phase: offset, duration, each zone's valve).
- `sensor.<controller>_phase_<n>` (s) - per-phase runtime, named `Phase n (zone, zone)`.
- `sensor.<controller>_start_time` (timestamp) - when to start.
- `binary_sensor.<controller>_skip` - on when the **weather entity**'s daily forecast rainfall
  is at or above the threshold.

Because the minimum interval is **per zone**, a zone that just ran does not block the others:
each zone becomes due again on its own schedule. After watering, your automation calls
`easy_irrigation.register_irrigation` on each watered zone (refills its bucket, stamps the
date). Set the same interval on all zones if you want them to batch onto shared watering nights.

Your automation triggers at `start_time` (when `skip` is off), reads the `plan` attribute and
opens each phase's valves for their durations, then calls `register_irrigation` per zone.

## Development

The FAO-56 maths (`et0.py`) and the scheduling maths (`schedule_math.py`) have no Home
Assistant dependencies and are unit-tested: `pytest tests/`.

## Roadmap

- [x] In-house FAO-56 ET0 from local weather sensors.
- [x] Multi-zone scheduler: finish at `sunrise - offset`; on-demand phases (parallel groups)
      with duplicate-zone exclusion and per-phase entities `Phase n (zones)`.
- [x] Weather-based skip from a weather entity's rain forecast.
- [x] Per-zone valve entity, surfaced in the controller's plan.
- [x] `register_irrigation` service + per-zone minimum days between irrigations.
- [x] English + German translations.
- [ ] Optional built-in valve execution.
- [ ] Number entities for live per-zone tuning.

## License

MIT - see [LICENSE](LICENSE).
