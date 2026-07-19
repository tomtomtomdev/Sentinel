"""Pure token-bucket logic for rate limiting (S14.4, SPEC §6). `now` is injected
so refill is deterministic (PLAN D4); the function never raises and never lets a
bucket exceed its capacity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sentinel.domain.logic.rate_limit import RateLimitConfig, consume, new_bucket

T0 = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
# capacity 3, one token back per second (window of 3s to fully refill)
CONFIG = RateLimitConfig(capacity=3.0, refill_per_second=1.0)


def test_new_bucket_starts_full() -> None:
    bucket = new_bucket(CONFIG, T0)
    assert bucket.tokens == CONFIG.capacity
    assert bucket.updated_at == T0


def test_consume_allows_until_empty_then_denies() -> None:
    bucket = new_bucket(CONFIG, T0)
    for _ in range(3):  # capacity == 3
        bucket, allowed = consume(bucket, CONFIG, T0)
        assert allowed
    bucket, allowed = consume(bucket, CONFIG, T0)
    assert not allowed
    assert bucket.tokens == pytest.approx(0.0)


def test_refill_lets_a_denied_key_through_after_enough_time() -> None:
    bucket = new_bucket(CONFIG, T0)
    for _ in range(3):
        bucket, _ = consume(bucket, CONFIG, T0)  # drain
    _, allowed = consume(bucket, CONFIG, T0)
    assert not allowed

    # One second later exactly one token has refilled.
    bucket, allowed = consume(bucket, CONFIG, T0 + timedelta(seconds=1))
    assert allowed


def test_partial_refill_is_not_enough() -> None:
    bucket = new_bucket(CONFIG, T0)
    for _ in range(3):
        bucket, _ = consume(bucket, CONFIG, T0)  # drain
    # Half a second → only 0.5 tokens, below the cost of 1.
    bucket, allowed = consume(bucket, CONFIG, T0 + timedelta(seconds=0.5))
    assert not allowed
    assert bucket.tokens == pytest.approx(0.5)


def test_refill_never_exceeds_capacity() -> None:
    bucket = new_bucket(CONFIG, T0)
    bucket, _ = consume(bucket, CONFIG, T0)  # 2 tokens left
    # A long idle period: tokens cap at capacity, not capacity + elapsed*rate.
    bucket, allowed = consume(bucket, CONFIG, T0 + timedelta(hours=1))
    assert allowed
    assert bucket.tokens == pytest.approx(CONFIG.capacity - 1)


def test_clock_going_backwards_does_not_add_tokens() -> None:
    bucket = new_bucket(CONFIG, T0)
    for _ in range(3):
        bucket, _ = consume(bucket, CONFIG, T0)  # drain
    # An earlier `now` (clock skew) must not refill or crash.
    bucket, allowed = consume(bucket, CONFIG, T0 - timedelta(seconds=10))
    assert not allowed


def test_per_window_derives_refill_rate() -> None:
    config = RateLimitConfig.per_window(max_events=10, window_seconds=60)
    assert config.capacity == 10.0
    assert config.refill_per_second == pytest.approx(10 / 60)


@pytest.mark.parametrize(("max_events", "window_seconds"), [(0, 60), (10, 0), (10, -5)])
def test_per_window_rejects_non_positive_parameters(max_events: int, window_seconds: float) -> None:
    with pytest.raises(ValueError):
        RateLimitConfig.per_window(max_events=max_events, window_seconds=window_seconds)
