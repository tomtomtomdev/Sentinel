"""In-process token-bucket rate limiter (S14.4, SPEC §6). Implements the
`RateLimiter` port with a per-key bucket held in memory, driven by the injected
`Clock` and the pure `consume` decision. One instance per running app (see
`interface/api/deps.py`); a Redis-backed limiter can drop in behind the same port
for a multi-instance deploy."""

from __future__ import annotations

import asyncio

from sentinel.domain.logic.rate_limit import BucketState, RateLimitConfig, consume, new_bucket
from sentinel.domain.ports import Clock


class InProcessRateLimiter:
    def __init__(self, *, clock: Clock, config: RateLimitConfig) -> None:
        self._clock = clock
        self._config = config
        self._buckets: dict[str, BucketState] = {}
        # `allow` reads-then-writes a bucket; a lock keeps concurrent requests for
        # the same key from racing on that read-modify-write.
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        now = self._clock.now()
        async with self._lock:
            state = self._buckets.get(key) or new_bucket(self._config, now)
            state, allowed = consume(state, self._config, now)
            self._buckets[key] = state
            return allowed
