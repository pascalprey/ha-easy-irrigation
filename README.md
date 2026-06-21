# Easy Irrigation (Home Assistant)

A lightweight, transparent soil-moisture **bucket** irrigation helper for Home Assistant.

It tracks a per-zone water balance (the "bucket") in millimetres: each day it subtracts the
net evapotranspiration (ET0 minus rainfall) and, once the bucket runs dry, computes how long
that zone needs to be watered. The actual valve switching stays in **your** automations - this
integration is the "brain" (buckets + durations + a start plan), not the "hands".

> **Status:** v0.9. One zone = one config entry; a schedule controller and an Open-Meteo data
> source are separate entries. The UI is available in English and German (chosen by your Home
> Assistant language). The controller can run the whole day on its own (daily calculation +
> optional valve switching), so a fully automation-free setup is possible, and ET0 can come
> straight from Open-Meteo with no helper sensors.

## Why

General-purpose irrigation integrations carry a lot of machinery (multiple weather backends,
sensor groups, calendars, custom frontends). This one is deliberately small: bring your own
ET0 (or let it compute ET0 from weather sensors), configure your zones, done.

## Installation (HACS custom repository)

1. HACS -> Integrations -> menu -> **Custom repositories** -> add this repository (category:
   *Integration*).
2. Install **Easy Irrigation**, then restart Home Assistant.
3. **Settings -> Devices & Services -> Add Integration -> Easy Irrigation**, then pick *zone*,
   *schedule controller*, or *Open-Meteo data source*.

## Zones

Add a zone and pick its **ET0 source** - how the daily net evapotranspiration (ET0 minus
rainfall, in mm) is obtained:

1. **Open-Meteo (built-in)** - *recommended.* No sensor, no YAML: add an **Open-Meteo data
   source** once (coordinates default to your Home Assistant location) and zones read the net
   ET0 from it. See [Open-Meteo data source](#open-meteo-data-source).
2. **From an ET0 sensor** - point at any sensor that already gives the daily net ET in mm.
3. **FAO-56 from weather sensors** - compute ET0 locally from your own daily-aggregated weather
   sensors. See [FAO-56 from your own sensors](#fao-56-from-your-own-sensors).

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

Per zone, per day: `bucket = min(bucket - net_ET0, max_bucket)`. On every `calculate` the
duration is recomputed: when `bucket < 0` **and** the zone's minimum interval has elapsed,
`duration = |bucket| / (flow_lpm*60/area_m2) * 3600 * multiplier + lead_time` (capped at
`max_duration`), else `0`.

The day's net ET0 is applied **once and then refreshed** to the latest value on every later
`calculate` of the same day - only the change since the previous call is booked. So calling
`calculate` repeatedly never double-counts, yet the bucket always reflects the newest value
(e.g. an early run that used a still-firming forecast is corrected by the evening run). Pick a
late `calc_time` so the figure is the day's actual value rather than a morning forecast.

> All sensor values are parsed comma-tolerantly (`"3,86"` works as well as `"3.86"`), so a
> localised sensor never breaks the calculation.

### Open-Meteo data source

Add Integration -> Easy Irrigation -> **Open-Meteo data source**. Latitude/longitude default to
your Home Assistant location (override if you like); the integration fetches the daily reference
ET0 and rainfall itself and exposes one diagnostic **Net ET0** sensor (gross ET0 and rainfall as
attributes). Every zone set to the Open-Meteo source - and, optionally, the controller's rain
skip - reads from this single shared fetch, so there is no REST sensor and no template to set up.

> **Attribution & licence.** Weather data by [Open-Meteo.com](https://open-meteo.com) under
> CC BY 4.0. Open-Meteo's free API needs no key and is for **non-commercial** use; stay within
> their fair-use limits.

### FAO-56 from your own sensors

The FAO-56 source expects **daily-aggregated** inputs (daily min/max temperature, mean humidity
or dew point, mean wind, optional daily solar in MJ/m²/day and daily rainfall). Home Assistant's
built-in helpers turn live sensors into those daily values:

- **Daily min/max temperature** - a `statistics` helper on your outdoor temperature sensor
  (characteristic *value_min* / *value_max*, sampling period 1 day).
- **Mean humidity / wind** - a `statistics` helper (characteristic *average_linear*, period 1 day).
- **Solar (MJ/m²/day)** - integrate a live W/m² sensor with an `integration` (Riemann-sum) helper
  to get Wh/m², reset daily with a `utility_meter`, then multiply by `0.0036` to get MJ/m²/day.
- **Daily rainfall** - a `utility_meter` (daily cycle) on a rain sensor.

If that is a lot of helpers, use the **Open-Meteo (built-in)** source instead - it does the
FAO-56 for you.

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
- `binary_sensor.<controller>_skip` - on when the forecast daily rainfall is at or above the
  threshold. The forecast comes from the configurable **rain source**: a `weather.*` entity, or
  the built-in **Open-Meteo** source (so one data source can drive both ET0 and the rain skip).
- a **Next watering** timestamp sensor *per zone*, attached to that zone's device so it sits
  next to the zone's bucket/duration. Its value is the zone's own valve-open time
  (`start_time` + the phase offset); it is `unknown` when the zone is not scheduled, with a
  `status` attribute saying why (`scheduled`, `not_due`, `rain_skip`, `no_schedule`) and a
  `skip` attribute mirroring the rain-skip flag. This makes "when does this zone water next,
  and is it being skipped?" visible at a glance.

Because the minimum interval is **per zone**, a zone that just ran does not block the others:
each zone becomes due again on its own schedule. After watering, your automation calls
`easy_irrigation.register_irrigation` on each watered zone (refills its bucket, stamps the
date). Set the same interval on all zones if you want them to batch onto shared watering nights.

### Running the day automatically

The controller has two settings that let it run without any automation:

- **Time of the daily calculation** (`calc_time`, default `23:00`): the controller applies the
  daily net-ET0 depletion to every zone at this time and refreshes the plan. Pick a time late in
  the day so the ET figure is the day's *actual* value rather than a morning forecast. This alone
  replaces a "call `calculate` once a day" automation.
- **Let this controller switch the valves itself** (`run_valves`, default off): at `start_time`
  the controller opens each phase's valves for their durations (phases sequentially, zones within
  a phase in parallel), then calls `register_irrigation` for each watered zone. With this on, the
  integration needs **no automation at all**. In this mode the controller also closes all its
  valves on load, so a restart that interrupted a run cannot leave a valve open.

To run the plan on demand - to test the wiring without waiting for the scheduled time - call the
`easy_irrigation.run_schedule` service on a controller entity. `ignore_skip` (default on) runs
through an active rain skip, and `test_seconds` runs each due zone for a few seconds without
registering the watering (a pure hardware/orchestration check that leaves the buckets untouched).

If you prefer to keep control in your own automation, leave `run_valves` off: trigger at
`start_time` (when `skip` is off), read the `plan` attribute and open each phase's valves for their
durations, then call `register_irrigation` per zone.

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
- [x] Built-in daily calculation at a configurable time (no automation needed).
- [x] Optional built-in valve execution (fully automation-free watering).
- [x] Refresh model: a later `calculate` uses the newest net-ET0 without double-counting.
- [x] `run_schedule` service to run/test the plan on demand.
- [x] Built-in Open-Meteo ET0 source (no REST sensor) + selectable rain source.
- [ ] Number entities for live per-zone tuning.

## License

MIT - see [LICENSE](LICENSE).
