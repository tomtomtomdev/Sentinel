"""Real `Clock` adapter. The only place in production code that reads wall time;
domain and application layers take it as a port so time stays deterministic in
tests (PLAN D4)."""

from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
