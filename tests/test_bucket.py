"""Unit tests for the pure bucket maths (no Home Assistant needed)."""

import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "easy_irrigation"),
)

import bucket_math  # noqa: E402

apply = bucket_math.apply_net_et0
MAXB = 20.0


def test_new_day_applies_net_once():
    """A new calendar day subtracts the full net and records it."""
    bucket, date, applied = apply(
        bucket=0.0, et0_date="2026-06-18", et0_applied=5.0,
        today="2026-06-19", net=3.6, max_bucket=MAXB,
    )
    assert round(bucket, 2) == -3.6
    assert date == "2026-06-19"
    assert applied == 3.6


def test_same_day_same_value_is_idempotent():
    """Re-calculating the same day with the same net changes nothing."""
    bucket, date, applied = apply(
        bucket=-3.6, et0_date="2026-06-19", et0_applied=3.6,
        today="2026-06-19", net=3.6, max_bucket=MAXB,
    )
    assert round(bucket, 2) == -3.6
    assert applied == 3.6


def test_same_day_books_only_the_increase():
    """A later, higher net subtracts only the delta (no double-count)."""
    bucket, _date, applied = apply(
        bucket=-3.6, et0_date="2026-06-19", et0_applied=3.6,
        today="2026-06-19", net=4.0, max_bucket=MAXB,
    )
    assert round(bucket, 2) == -4.0  # only the extra 0.4 was booked
    assert applied == 4.0


def test_same_day_rain_adds_water_back():
    """If the net drops (rain), the previously booked amount is partly undone."""
    bucket, _date, applied = apply(
        bucket=-3.6, et0_date="2026-06-19", et0_applied=3.6,
        today="2026-06-19", net=-1.0, max_bucket=MAXB,
    )
    assert round(bucket, 2) == 1.0  # -3.6 - (-1.0 - 3.6) = +1.0
    assert applied == -1.0


def test_none_net_leaves_state_untouched():
    """An unavailable sensor (net None) must not change anything."""
    state = apply(
        bucket=-3.6, et0_date="2026-06-19", et0_applied=3.6,
        today="2026-06-19", net=None, max_bucket=MAXB,
    )
    assert state == (-3.6, "2026-06-19", 3.6)


def test_legacy_entry_adopts_baseline_without_double_counting():
    """A pre-refresh bucket already applied today only adopts the baseline."""
    bucket, date, applied = apply(
        bucket=-3.6, et0_date="2026-06-19", et0_applied=None,
        today="2026-06-19", net=3.6, max_bucket=MAXB,
    )
    assert round(bucket, 2) == -3.6  # NOT -7.2
    assert date == "2026-06-19"
    assert applied == 3.6


def test_bucket_capped_at_max():
    """Heavy rain on a new day refills but never above the maximum."""
    bucket, _date, _applied = apply(
        bucket=18.0, et0_date="2026-06-18", et0_applied=0.0,
        today="2026-06-19", net=-10.0, max_bucket=MAXB,
    )
    assert bucket == MAXB
