"""Pure token-bucket rate limiting (S14.4, SPEC §6).

The *decision* — how many tokens a bucket holds now and whether one more event is
allowed — is a pure function of (prior state, elapsed time, config). Storage of
per-key state and the current time are adapter concerns (see
`infrastructure/rate_limit.py`), so this module has no I/O and reads no clock:
`now` is injected (PLAN D4), making refill deterministic in tests. Nothing here
raises on the hot path — a rate limiter must never crash the request it guards.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RateLimitConfig:
    """Token-bucket parameters: `capacity` tokens, accruing at `refill_per_second`
    (capped at `capacity`). Each limited event costs one token."""

    capacity: float
    refill_per_second: float

    @classmethod
    def per_window(cls, *, max_events: int, window_seconds: float) -> RateLimitConfig:
        """A bucket that permits `max_events` before throttling and fully refills
        over `window_seconds`. Rejects non-positive parameters so misconfiguration
        fails at boot rather than silently disabling (or wedging) the limiter."""
        if max_events < 1:
            raise ValueError("max_events must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        return cls(capacity=float(max_events), refill_per_second=max_events / window_seconds)


@dataclass(frozen=True)
class BucketState:
    """A bucket's available tokens as of `updated_at`."""

    tokens: float
    updated_at: datetime


def new_bucket(config: RateLimitConfig, now: datetime) -> BucketState:
    """A full bucket — a never-before-seen key starts allowed."""
    return BucketState(tokens=config.capacity, updated_at=now)


def consume(
    state: BucketState, config: RateLimitConfig, now: datetime, cost: float = 1.0
) -> tuple[BucketState, bool]:
    """Refill for the time elapsed since `state.updated_at` (capped at capacity),
    then try to take `cost` tokens. Returns the new state and whether the take
    succeeded. Elapsed time is clamped at zero so a backwards clock never mints
    tokens or crashes."""
    elapsed = max(0.0, (now - state.updated_at).total_seconds())
    tokens = min(config.capacity, state.tokens + elapsed * config.refill_per_second)
    if tokens >= cost:
        return BucketState(tokens - cost, now), True
    return BucketState(tokens, now), False
