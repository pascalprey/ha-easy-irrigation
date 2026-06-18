"""Unit tests for the pure scheduling maths (no Home Assistant needed)."""

import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "easy_irrigation"),
)

import schedule_math  # noqa: E402


def test_sequential_sums_durations():
    """Each zone in its own stage -> total is the sum."""
    result = schedule_math.compute_schedule({1: [600], 2: [300], 3: [1200]}, target_epoch=10_000)
    assert result["total"] == 2100
    assert result["start_epoch"] == 10_000 - 2100
    assert result["stage_offsets"] == {1: 0, 2: 600, 3: 900}


def test_parallel_stage_takes_longest():
    """Zones sharing a stage run in parallel -> stage = max, shorter total."""
    result = schedule_math.compute_schedule({1: [600, 300, 1200], 2: [200]}, target_epoch=10_000)
    assert result["total"] == 1200 + 200
    assert result["stage_durations"] == {1: 1200, 2: 200}


def test_empty_and_unknown_target():
    result = schedule_math.compute_schedule({}, target_epoch=None)
    assert result["total"] == 0
    assert result["start_epoch"] is None


def test_parallel_is_shorter_than_sequential():
    seq = schedule_math.compute_schedule({1: [600], 2: [900]}, 0)["total"]
    par = schedule_math.compute_schedule({1: [600, 900]}, 0)["total"]
    assert par < seq
    assert par == 900 and seq == 1500
