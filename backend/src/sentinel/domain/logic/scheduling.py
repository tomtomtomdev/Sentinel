"""Pure scheduling decisions for the runner (SPEC §3.3). Zero I/O: `now` and the
per-monitor last-run times are passed in, so *what* to probe and *when* are fully
deterministic and exhaustively unit-testable (PLAN D4). The async runner
(`infrastructure/scheduler.py`) is a thin loop over these decisions.

Two rules from SPEC §3.3 live here:

- **Jitter** — each monitor's next run is offset by a deterministic per-monitor
  amount so checks don't all fire on the interval boundary (thundering herd). The
  offset is derived from the monitor id (no RNG), so it's stable across cycles and
  processes and tests can assert exact values. Jitter is **non-negative** (it only
  ever delays), which preserves the "not before `interval`" guarantee in §7.
- **Skip, don't backfill** — selection is a boolean (due / not due), so a monitor
  is returned at most once per cycle no matter how many intervals were missed while
  the worker was down. The runner then records the run time as the new last-run, so
  the schedule resets relative to `now` rather than replaying missed ticks.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sentinel.domain.entities import Monitor

# Spread the next run over up to this fraction of the interval. Small enough to
# barely delay a check, large enough to de-bunch a herd on the minute boundary.
JITTER_FRACTION = 0.1


def jitter_seconds(monitor_id: UUID, interval_seconds: int) -> int:
    """A deterministic per-monitor offset in ``[0, interval * JITTER_FRACTION)``.

    Derived from the monitor id so it's stable (no clock, no RNG) and well spread
    across monitors (UUIDs are uniform), letting tests assert exact values.
    """
    window = max(1, int(interval_seconds * JITTER_FRACTION))
    return int.from_bytes(monitor_id.bytes, "big") % window


def next_run_at(monitor: Monitor, last_run_at: datetime) -> datetime:
    """When `monitor` becomes due again after a run at `last_run_at`: one interval
    plus the monitor's fixed jitter. Computed from the *actual* last run, so a gap
    is skipped rather than backfilled (see module docstring)."""
    delay = monitor.interval_seconds + jitter_seconds(monitor.id, monitor.interval_seconds)
    return last_run_at + timedelta(seconds=delay)


def select_due_monitors(
    monitors: list[Monitor],
    now: datetime,
    last_run_by_id: dict[UUID, datetime],
) -> list[Monitor]:
    """The enabled monitors due to be probed at `now`, in input order.

    A monitor is due when it has never run (absent from `last_run_by_id`) or when
    `now` has reached its `next_run_at`. Disabled monitors are never selected
    (SPEC §3.3). Each due monitor appears exactly once — missed ticks are skipped,
    not backfilled.
    """
    due: list[Monitor] = []
    for monitor in monitors:
        if not monitor.enabled:
            continue
        last_run = last_run_by_id.get(monitor.id)
        if last_run is None or now >= next_run_at(monitor, last_run):
            due.append(monitor)
    return due
