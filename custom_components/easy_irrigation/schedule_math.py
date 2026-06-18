"""Pure scheduling maths for the watering plan (no Home Assistant deps).

Stages run sequentially; zones within a stage run in parallel. A stage therefore
takes as long as its longest zone, and the total runtime is the sum over stages.
"""

from __future__ import annotations


def compute_schedule(
    stages: dict[int, list[float]], target_epoch: float | None
) -> dict:
    """Compute total runtime, per-stage offsets and the start time.

    Args:
        stages: ``{stage_index: [zone_durations_in_seconds, ...]}``. Empty stages
            (no due zones) contribute zero.
        target_epoch: desired finish time as a POSIX timestamp, or ``None`` if it
            is currently unknown (then ``start_epoch`` is ``None``).

    Returns a dict with ``total`` (s), ``start_epoch``, ``stage_durations`` and
    ``stage_offsets`` (seconds after start at which each stage begins).
    """
    durations = {stage: (max(values) if values else 0.0) for stage, values in stages.items()}
    order = sorted(durations)

    total = sum(durations[stage] for stage in order)

    offsets: dict[int, float] = {}
    elapsed = 0.0
    for stage in order:
        offsets[stage] = elapsed
        elapsed += durations[stage]

    start_epoch = None if target_epoch is None else target_epoch - total
    return {
        "total": total,
        "start_epoch": start_epoch,
        "stage_durations": durations,
        "stage_offsets": offsets,
    }
