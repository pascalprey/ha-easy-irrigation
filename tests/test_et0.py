"""Unit tests for the FAO-56 evapotranspiration maths.

``et0`` has no Home Assistant dependencies, so these run with plain pytest.
"""

import math
import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "easy_irrigation"),
)

import et0  # noqa: E402


def test_reference_example_matches_fao56():
    """FAO-56 worked example (lat 50.80N, 100 m, DOY 187) -> ET0 = 3.88 mm/day."""
    ea = et0.avp_from_rh(12.3, 21.5, rh_min=63, rh_max=84)
    value = et0.et0_fao56(
        tmin=12.3,
        tmax=21.5,
        rs=22.07,
        u2=2.078,
        ea=ea,
        elevation_m=100,
        lat_rad=math.radians(50.80),
        doy=187,
    )
    assert abs(ea - 1.409) < 0.01
    assert abs(value - 3.88) < 0.05


def test_solar_radiation_estimated_when_missing():
    """Without measured Rs, Hargreaves estimation stays in a sane range."""
    ea = et0.avp_from_rh(12.3, 21.5, rh_min=63, rh_max=84)
    value = et0.et0_fao56(
        tmin=12.3,
        tmax=21.5,
        rs=None,
        u2=2.078,
        ea=ea,
        elevation_m=100,
        lat_rad=math.radians(50.80),
        doy=187,
    )
    assert 3.0 < value < 4.5


def test_dewpoint_vapour_pressure():
    """ea from dew point equals the saturation vapour pressure at Tdew."""
    assert math.isclose(et0.avp_from_dewpoint(10.0), et0.svp(10.0), rel_tol=1e-9)
