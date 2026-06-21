# Easy Irrigation: full guide

This guide explains what the integration does, how every setting works, and why the design is the
way it is. It is meant to be read top to bottom once, then used as a reference.

## Contents

1. [Overview and philosophy](#1-overview-and-philosophy)
2. [The bucket model](#2-the-bucket-model)
3. [ET0 sources](#3-et0-sources)
4. [Zones](#4-zones)
5. [The schedule controller](#5-the-schedule-controller)
6. [Running the day: automation-free or your own automation](#6-running-the-day)
7. [Service reference](#7-service-reference)
8. [Step by step setup](#8-step-by-step-setup)
9. [Troubleshooting and FAQ](#9-troubleshooting-and-faq)
10. [Design decisions and rationale](#10-design-decisions-and-rationale)
11. [Attribution and licence](#11-attribution-and-licence)

---

## 1. Overview and philosophy

Easy Irrigation is a soil moisture "bucket" helper. For each zone it keeps a running water balance
in millimetres. Every day it subtracts the net evapotranspiration (reference ET0 minus rainfall),
and once a zone has built up a deficit it computes how long that zone needs to run to make the
deficit good again.

The integration is the brain, not the hands. It produces buckets, durations, and a start plan.
Switching the valves can be done in two ways: by your own automation that reads the plan, or by the
controller itself (see [section 6](#6-running-the-day)).

The design goal is to stay small and transparent. There is no proprietary frontend and no hidden
state. Every number that drives a decision is visible as a sensor or a sensor attribute, and the
core maths live in three dependency free modules that are unit tested.

## 2. The bucket model

### What the bucket means

The bucket is the water balance of the root zone relative to **field capacity**.

* `bucket = 0` means the soil is at field capacity, which is "full" for the plant.
* `bucket < 0` is a deficit. The plant has used water that has not been replaced yet.
* `bucket > 0` is a surplus above field capacity. It only appears after rain and acts as a buffer
  that delays the next watering. It is capped at `max_bucket`.

### Daily depletion

Once per calendar day the net ET0 is subtracted:

```
bucket = min(bucket - net_ET0, max_bucket)
```

`net_ET0` already has rainfall removed (ET0 minus rain), so on a wet day the net value is negative
and the bucket gains water instead of losing it.

### The refresh model

Calling the calculation more than once on the same day does not double count. The day's net value
is booked **once** and then refreshed to the latest value on every later call of the same day. Only
the change since the previous call is applied. Two consequences follow.

* You can recalculate at any time during the day without corrupting the bucket.
* A calculation done early with a still firming forecast is automatically corrected by a later
  calculation with the near final value.

A bucket that was saved before this model existed is migrated safely: on the first calculation of
an already booked day it adopts the current value as its baseline instead of subtracting again.

### From bucket to run time

On every calculation the duration is recomputed. When the bucket is negative and the zone's minimum
interval has elapsed:

```
duration = |bucket| / (flow_lpm * 60 / area_m2) * 3600 * multiplier + lead_time
```

capped at `max_duration`. Otherwise the duration is `0`, which tells the controller to skip that
zone. `flow_lpm * 60 / area_m2` is the precipitation rate of the zone in millimetres per hour, so
the formula is "how long at this precipitation rate to put back the missing millimetres", scaled by
the multiplier and with a fixed lead time added.

> All numeric sensor values are parsed comma tolerantly, so `"3,86"` works as well as `"3.86"` and a
> localised sensor never breaks the calculation.

## 3. ET0 sources

Each zone chooses how its daily net ET0 is obtained. There are three options.

### Open-Meteo (recommended, built-in)

Pick this and the zone fetches the daily reference ET0 and rainfall straight from Open-Meteo, using
your Home Assistant location. No sensor, no YAML, no template, and no separate entry. The net value
(ET0 minus rainfall) is used for the bucket and is shown on the per zone `sensor.<zone>_net_et0`,
with the gross ET0, the rainfall, and the forecast date as attributes.

The fetch happens at calculation time and is cached for about thirty minutes per location, so many
Open-Meteo zones plus the controller's rain skip share a single request rather than each making
their own.

#### What the Open-Meteo daily ET0 actually is

Open-Meteo's `et0_fao_evapotranspiration` daily value is the **daily sum** of the hourly reference
ET0 for that calendar day, computed with the FAO-56 Penman-Monteith method. It is a forecast that
Open-Meteo re-issues as new model runs arrive and as the day's early hours turn into actuals.
Reading it early in the morning gives a speculative value that keeps changing through the day.
Reading it late in the evening gives a value that is essentially final. This is the reason the daily
calculation defaults to 23:00 (see [calc_time](#calc_time-the-daily-calculation)).

### From an ET0 sensor

Point the zone at any sensor that already provides the daily net ET (ET0 minus rainfall) in
millimetres. Use this if you already produce an ET0 figure some other way.

### FAO-56 from your own weather sensors

Compute ET0 locally from your own station. This source expects **daily aggregated** inputs, not live
readings: daily minimum and maximum temperature, mean humidity or dew point, mean wind, and
optionally daily solar radiation in MJ/m²/day and daily rainfall. Location and elevation come from
Home Assistant.

Home Assistant's built-in helpers produce those daily figures from live sensors:

* Daily minimum and maximum temperature: a `statistics` helper on the outdoor temperature sensor
  (characteristic `value_min` and `value_max`, sampling period one day).
* Mean humidity and mean wind: a `statistics` helper (characteristic `average_linear`, period one
  day).
* Solar in MJ/m²/day: integrate a live W/m² sensor with an `integration` (Riemann sum) helper to get
  Wh/m², reset it daily with a `utility_meter`, then multiply by `0.0036`.
* Daily rainfall: a `utility_meter` on a daily cycle over a rain sensor.

If this feels like a lot of helpers, use the Open-Meteo source instead. It does the FAO-56 for you.

## 4. Zones

A zone is one config entry. Add it via Settings, Devices and Services, Add Integration, Easy
Irrigation, then pick "Add a watering zone".

### Parameters

| Field | Meaning |
|---|---|
| Valve | Optional `switch` or `valve` entity for the zone. Used by the controller's plan and by `run_valves`. |
| Area (m²) | Watered area of the zone. |
| Flow rate (L/min) | Combined output of all emitters in the zone. |
| Maximum bucket (mm) | Cap on the surplus above field capacity (the rain buffer). |
| Multiplier | Per zone scaling of the run time (a crop or efficiency factor). |
| Lead time (s) | A fixed time added to every run. |
| Maximum duration (s) | Hard cap on a single run. |
| Drainage rate (mm/h) | Optional drainage of excess near saturation. `0` turns it off. |
| Minimum days between irrigations | The zone reports duration `0` until this many days have passed since it last watered, which gives deep and infrequent watering. `0` turns it off. |

### Sensors per zone

| Entity | Meaning |
|---|---|
| `sensor.<zone>_bucket` | Current water balance in mm. |
| `sensor.<zone>_duration` | Recommended run time in seconds (`0` when not due). |
| `sensor.<zone>_net_et0` | Net ET0 (ET0 minus rainfall) last applied, in mm. For Open-Meteo zones it carries gross ET0, rainfall, and date as attributes. |
| `sensor.<zone>_next_watering` | Timestamp of the zone's next watering, or `unknown` with a `status` attribute (see the controller section). |

## 5. The schedule controller

The controller is a second config entry that aggregates your zones into one nightly plan. After its
settings you assign zones to **phases**, one phase at a time. Zones already used are hidden from
later phases.

Phases run one after another. Zones inside a phase run at the same time:

```
phase_runtime = max(durations of the due zones in that phase)
total_runtime = sum of all phase runtimes
start_time    = next_sunrise - sunrise_offset - total_runtime
```

So watering finishes `sunrise_offset` minutes before sunrise.

### Controller settings

| Setting | Meaning |
|---|---|
| Sunrise offset (min) | How many minutes before sunrise the watering should finish. |
| Time of the daily calculation (`calc_time`) | When the controller recalculates all its zones. Default 23:00. |
| Let this controller switch the valves itself (`run_valves`) | When on, the controller drives the valves at the start time. Default off. |
| Rain forecast source | Where the rain skip reads its forecast: a `weather` entity or the built-in Open-Meteo fetch. |
| Skip threshold (mm) | The rain skip turns on when the forecast daily rainfall is at or above this value. |

#### calc_time, the daily calculation

At `calc_time` the controller runs the calculation on every zone it schedules, then rebuilds the
plan. Choose a time late in the day so each zone uses the day's actual ET, not a morning forecast.
This replaces a "call calculate once a day" automation. It runs regardless of the `run_valves`
setting.

### Controller sensors

| Entity | Meaning |
|---|---|
| `sensor.<controller>_total_runtime` | Total run time in seconds. Attributes: `stage_durations`, `stage_offsets`, `skip`, and a full `plan` (per phase the offset, the duration, and each zone's valve). |
| `sensor.<controller>_phase_<n>` | Run time of phase n, named `Phase n (zone, zone)`. |
| `sensor.<controller>_start_time` | When watering should start. |
| `binary_sensor.<controller>_skip` | On when the forecast daily rainfall is at or above the threshold. |

Each zone also gets a `sensor.<zone>_next_watering` timestamp that lives on the zone device. Its
value is the zone's own valve open time (start time plus its phase offset). It is `unknown` when the
zone is not scheduled, and the `status` attribute says why: `scheduled`, `not_due`, `rain_skip`, or
`no_schedule`. A `skip` attribute mirrors the rain skip flag. This makes "when does this zone water
next, and is it being skipped" visible at a glance.

Because the minimum interval is per zone, a zone that just ran does not block the others. Set the
same interval on all zones if you want them to batch onto shared watering nights.

## 6. Running the day

### Option A: the controller switches the valves (no automation)

Turn on `run_valves`. At the start time the controller opens each phase's valves for their
durations (phases one after another, zones within a phase together), then calls
`register_irrigation` for each watered zone. With this on the integration needs no automation at
all.

Safety: in this mode the controller closes all its valves when it loads, so a restart that
interrupted a run cannot leave a valve open. The start timer is only armed for a start time in the
future, which prevents it from firing again right after a run finishes. A run in progress is
cancelled cleanly when the entry unloads.

### Option B: your own automation

Leave `run_valves` off and trigger your automation at `sensor.<controller>_start_time` when the
skip binary sensor is off. Read the `plan` attribute of the total runtime sensor and open each
phase's valves for their durations, then call `easy_irrigation.register_irrigation` on each watered
zone.

### Testing on demand

Call `easy_irrigation.run_schedule` on a controller entity to run the current plan immediately,
without waiting for the start time. `ignore_skip` (default on) runs through an active rain skip, and
`test_seconds` runs each due zone for a few seconds without registering the watering. The second
option is a pure hardware and orchestration check that leaves the buckets untouched.

## 7. Service reference

All zone services target zone entities. `run_schedule` targets a controller entity.

| Service | Fields | Effect |
|---|---|---|
| `easy_irrigation.calculate` | none | Apply today's net ET0 to the targeted zone(s) using the refresh model, then recompute the duration. |
| `easy_irrigation.set_bucket` | `value` (mm) | Force the bucket to a value. Useful to seed a deficit for a test. |
| `easy_irrigation.reset_bucket` | none | Set the bucket to 0. |
| `easy_irrigation.register_irrigation` | `amount_mm` (optional) | Record a watering: refill the bucket (`amount_mm` mm, capped at the maximum, or back to 0 if omitted) and stamp today's date for the minimum interval. |
| `easy_irrigation.run_schedule` | `ignore_skip` (default true), `test_seconds` (optional) | Run the controller's current plan now. With `test_seconds` it does not register the watering. |

## 8. Step by step setup

1. Install Easy Irrigation through HACS as a custom repository (category Integration) and restart
   Home Assistant.
2. Add one zone per area: Add Integration, Easy Irrigation, "Add a watering zone". Name it, pick
   "Open-Meteo (recommended, built-in)" as the ET0 source, then fill in the zone parameters (valve,
   area, flow rate, and the rest). Repeat for every zone.
3. Add a schedule controller: Add Integration, Easy Irrigation, "Add a schedule controller". Set the
   sunrise offset, the calculation time, whether the controller should switch the valves, and the
   rain source with its threshold. Then assign zones to phases one phase at a time.
4. Optionally test with `easy_irrigation.run_schedule` using `test_seconds: 5` and
   `ignore_skip: true`.

## 9. Troubleshooting and FAQ

**A zone shows duration 0 and never waters.** It is not due. Either the bucket is not negative (no
deficit yet) or the minimum interval has not elapsed. You can seed a deficit for a test with
`set_bucket`.

**Calculating again gives no new bucket value.** That is the refresh model working. On the same day
with an unchanged net ET0 there is nothing new to apply. The bucket changes again on the next
calendar day or when the net value itself changes.

**Nothing waters tomorrow morning.** Check the rain skip. If rain at or above the threshold is
forecast, the run is skipped on purpose. The per zone `next_watering` sensor shows `status:
rain_skip` in that case.

**Two zones in one phase start a few seconds apart.** The integration sends both commands at the
same moment. A small gap is the valve hardware or its integration reporting state with a delay. For
example several relays on one Tasmota or similar device can confirm their state to Home Assistant
out of step. For a real run of many minutes this is irrelevant.

**The bucket sits at 0 after a watering and will not deplete on a recalculation the same day.** This
is correct. The day's ET was already booked before the watering, so re-running the calculation on
the same day does not re-subtract it. The next day's calculation depletes again.

## 10. Design decisions and rationale

**Refill to field capacity, not to maximum.** A watering brings the bucket back to 0, which is field
capacity. Water above field capacity drains below the root zone and is wasted, so the integration
never waters past it. `max_bucket` is the buffer that rain can fill, not an irrigation target. This
matches the FAO-56 idea of irrigating back to field capacity, and it matches how Smart Irrigation
behaves.

**Calculate at 23:00.** Open-Meteo's daily ET0 is a daily sum that is re-forecast through the day. A
late calculation uses the day's near final value and avoids watering on a speculative morning
forecast.

**The refresh model.** Booking the day's net once and then only applying the change keeps repeated
calculations from double counting, while still letting a later calculation pick up a newer value.
This is what makes "recalculate any time" safe.

**Open-Meteo as a per zone source, not a separate entry.** An earlier design had a dedicated
Open-Meteo data source entry. It was redundant with picking Open-Meteo in the zone, so it was
removed. The zone now fetches directly using the Home Assistant location, and a shared cache keeps
it to one request per location.

**Phases parallel within, sequential between.** This models a garden where a pump or pressure line
can drive a couple of zones at once but not all of them, while still finishing before sunrise.

## 11. Attribution and licence

Weather data is provided by [Open-Meteo.com](https://open-meteo.com) under the Creative Commons
Attribution 4.0 licence (CC BY 4.0). Open-Meteo's free API needs no key and is for non-commercial
use. Stay within their fair use limits.

The integration itself is released under the MIT licence. See [LICENSE](../LICENSE).
