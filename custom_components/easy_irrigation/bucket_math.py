"""Pure bucket update for the daily net-ET0 depletion (refresh model).

No Home Assistant imports, so it is unit-tested directly (``tests/test_bucket.py``).
"""

from __future__ import annotations


def apply_net_et0(
    *,
    bucket: float,
    et0_date: str | None,
    et0_applied: float | None,
    today: str,
    net: float | None,
    max_bucket: float,
    drainage: float = 0.0,
) -> tuple[float, str | None, float | None]:
    """Return ``(bucket, et0_date, et0_applied)`` after applying today's net ET0.

    The day's net ET0 (ET0 minus rainfall, in mm) is applied **once** and then
    *refreshed* to the latest value on every later calculation of the same day:
    only the change since the previous calculation is booked, so calling
    ``calculate`` repeatedly never double-counts, yet the bucket always reflects
    the newest value. A new calendar day applies the full net afresh; drainage
    near saturation is applied once per day (on that first calculation).

    ``et0_applied`` is ``None`` for buckets persisted before this model existed
    (the day was already applied under the old "apply once, then lock" guard);
    such a same-day entry adopts the current value as its baseline without
    re-subtracting, so upgrading mid-day cannot double-count.
    """
    if net is None:
        return bucket, et0_date, et0_applied

    if et0_date != today:
        # First calculation of a new day: apply the full net once (+ drainage).
        bucket -= net
        if bucket > 0 and drainage > 0 and max_bucket > 0:
            bucket -= drainage * 24 * (min(bucket, max_bucket) / max_bucket) ** 4
        bucket = min(bucket, max_bucket)
        return bucket, today, net

    if et0_applied is None:
        # Legacy same-day entry (old lock model): adopt the value as baseline.
        return bucket, et0_date, net

    # Same day: refresh to the latest net by booking only the change.
    delta = net - et0_applied
    if delta:
        bucket = min(bucket - delta, max_bucket)
    return bucket, et0_date, net
