"""FAO-56 Penman-Monteith reference evapotranspiration (daily).

Self-contained implementation of the procedure in Allen et al. (1998),
"Crop evapotranspiration - Guidelines for computing crop water requirements"
(FAO Irrigation and Drainage Paper 56). All inputs are daily values.
"""

from __future__ import annotations

import math

GSC = 0.0820  # solar constant [MJ m-2 min-1]
ALBEDO = 0.23  # reference grass albedo
SIGMA = 4.903e-9  # Stefan-Boltzmann constant [MJ K-4 m-2 day-1]


def svp(t: float) -> float:
    """Saturation vapour pressure [kPa] at air temperature t [°C]."""
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def svp_slope(t: float) -> float:
    """Slope of the saturation vapour pressure curve [kPa/°C]."""
    return 4098 * svp(t) / (t + 237.3) ** 2


def atmospheric_pressure(elevation_m: float) -> float:
    """Atmospheric pressure [kPa] from elevation [m]."""
    return 101.3 * ((293 - 0.0065 * elevation_m) / 293) ** 5.26


def psychrometric_constant(pressure_kpa: float) -> float:
    """Psychrometric constant [kPa/°C]."""
    return 0.000665 * pressure_kpa


def wind_speed_2m(wind: float, measure_height_m: float) -> float:
    """Adjust wind speed [m/s] measured at ``measure_height_m`` to 2 m."""
    if measure_height_m == 2:
        return wind
    return wind * 4.87 / math.log(67.8 * measure_height_m - 5.42)


def extraterrestrial_radiation(lat_rad: float, doy: int) -> float:
    """Extraterrestrial radiation Ra [MJ m-2 day-1]."""
    dr = 1 + 0.033 * math.cos(2 * math.pi / 365 * doy)
    decl = 0.409 * math.sin(2 * math.pi / 365 * doy - 1.39)
    sha = math.acos(max(-1.0, min(1.0, -math.tan(lat_rad) * math.tan(decl))))
    return (
        (24 * 60 / math.pi)
        * GSC
        * dr
        * (
            sha * math.sin(lat_rad) * math.sin(decl)
            + math.cos(lat_rad) * math.cos(decl) * math.sin(sha)
        )
    )


def daylight_hours(lat_rad: float, doy: int) -> float:
    """Maximum possible daylight hours N."""
    decl = 0.409 * math.sin(2 * math.pi / 365 * doy - 1.39)
    sha = math.acos(max(-1.0, min(1.0, -math.tan(lat_rad) * math.tan(decl))))
    return 24 / math.pi * sha


def avp_from_rh(
    tmin: float,
    tmax: float,
    rh_mean: float | None = None,
    rh_min: float | None = None,
    rh_max: float | None = None,
) -> float | None:
    """Actual vapour pressure ea [kPa] from relative humidity."""
    if rh_max is not None and rh_min is not None:
        return (svp(tmin) * rh_max / 100 + svp(tmax) * rh_min / 100) / 2
    if rh_mean is not None:
        return rh_mean / 100 * (svp(tmax) + svp(tmin)) / 2
    return None


def avp_from_dewpoint(tdew: float) -> float:
    """Actual vapour pressure ea [kPa] from dew-point temperature [°C]."""
    return svp(tdew)


def solar_radiation_from_sun_hours(
    sun_hours: float, daylight: float, ra: float, a_s: float = 0.25, b_s: float = 0.5
) -> float:
    """Estimate Rs [MJ m-2 day-1] from measured sunshine hours (Angstrom)."""
    return (a_s + b_s * (sun_hours / daylight if daylight > 0 else 0.0)) * ra


def solar_radiation_from_temp(
    tmin: float, tmax: float, ra: float, k_rs: float = 0.16
) -> float:
    """Estimate Rs [MJ m-2 day-1] from the temperature range (Hargreaves).

    ``k_rs`` ~0.16 for interior, ~0.19 for coastal locations.
    """
    return k_rs * math.sqrt(max(tmax - tmin, 0.0)) * ra


def et0_fao56(
    *,
    tmin: float,
    tmax: float,
    u2: float,
    ea: float,
    elevation_m: float,
    lat_rad: float,
    doy: int,
    rs: float | None = None,
    k_rs: float = 0.16,
) -> float:
    """Daily FAO-56 Penman-Monteith reference ET0 [mm/day].

    rs: incoming solar radiation [MJ m-2 day-1]; if ``None`` it is estimated
        from the temperature range (Hargreaves) using ``k_rs``.
    u2: wind speed at 2 m [m/s]
    ea: actual vapour pressure [kPa]
    """
    tmean = (tmax + tmin) / 2
    delta = svp_slope(tmean)
    gamma = psychrometric_constant(atmospheric_pressure(elevation_m))
    es = (svp(tmax) + svp(tmin)) / 2

    ra = extraterrestrial_radiation(lat_rad, doy)
    if rs is None:
        rs = solar_radiation_from_temp(tmin, tmax, ra, k_rs)
    rso = (0.75 + 2e-5 * elevation_m) * ra
    rs = min(rs, rso) if rso > 0 else rs  # measured/estimated Rs cannot exceed clear-sky

    rns = (1 - ALBEDO) * rs
    rel = min(rs / rso, 1.0) if rso > 0 else 0.0
    rnl = (
        SIGMA
        * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4)
        / 2
        * (0.34 - 0.14 * math.sqrt(max(ea, 0.0)))
        * (1.35 * rel - 0.35)
    )
    rn = rns - rnl
    g = 0.0  # daily soil heat flux is negligible

    numerator = 0.408 * delta * (rn - g) + gamma * (900 / (tmean + 273)) * u2 * (es - ea)
    denominator = delta + gamma * (1 + 0.34 * u2)
    return max(numerator / denominator, 0.0)
