"""In-process token-bucket rate limiter (S14.4). Keys (client IPs) get isolated
buckets; the injected `Clock` drives refill so the test is deterministic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sentinel.domain.logic.rate_limit import RateLimitConfig
from sentinel.infrastructure.rate_limit import InProcessRateLimiter
from tests.support.fakes import FixedClock

T0 = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
# capacity 2, refills one token per second
CONFIG = RateLimitConfig(capacity=2.0, refill_per_second=1.0)


async def test_allows_up_to_capacity_then_denies() -> None:
    limiter = InProcessRateLimiter(clock=FixedClock(T0), config=CONFIG)

    assert await limiter.allow("1.2.3.4") is True
    assert await limiter.allow("1.2.3.4") is True
    assert await limiter.allow("1.2.3.4") is False


async def test_keys_are_isolated() -> None:
    limiter = InProcessRateLimiter(clock=FixedClock(T0), config=CONFIG)

    assert await limiter.allow("1.2.3.4") is True
    assert await limiter.allow("1.2.3.4") is True
    assert await limiter.allow("1.2.3.4") is False
    # A different client is unaffected.
    assert await limiter.allow("9.9.9.9") is True


async def test_refills_as_the_clock_advances() -> None:
    clock = FixedClock(T0)
    limiter = InProcessRateLimiter(clock=clock, config=CONFIG)

    assert await limiter.allow("1.2.3.4") is True
    assert await limiter.allow("1.2.3.4") is True
    assert await limiter.allow("1.2.3.4") is False

    clock.set(T0 + timedelta(seconds=1))  # one token back
    assert await limiter.allow("1.2.3.4") is True
    assert await limiter.allow("1.2.3.4") is False
