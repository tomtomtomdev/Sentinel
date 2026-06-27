"""`Heartbeat` adapters — the scheduler's dead-man's switch (SPEC §6, PLAN D8).

`HttpxHeartbeat` pings an external watchdog (e.g. healthchecks.io) once per cycle;
if the worker dies the watchdog stops hearing it and alerts from outside, so a
silent crash is never mistaken for "all green". A ping **never raises** — a
watchdog outage must not take the runner down — so transport errors are swallowed
with a warning. `NullHeartbeat` is the inert no-op used when `HEARTBEAT_URL` is
unset, keeping the runner free of "is it configured?" branches."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 10.0


class NullHeartbeat:
    """No watchdog configured: pinging does nothing."""

    async def ping(self) -> None:
        return None


class HttpxHeartbeat:
    """GETs `url` each cycle. Owns a lazily-created shared `AsyncClient`; failures
    are logged, never raised, so a flaky watchdog can't crash the runner."""

    def __init__(
        self,
        url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
    ) -> None:
        self._url = url
        self._client = client or httpx.AsyncClient()
        self._timeout = timeout_seconds

    async def aclose(self) -> None:
        await self._client.aclose()

    async def ping(self) -> None:
        try:
            await self._client.get(self._url, timeout=self._timeout)
        except httpx.HTTPError as exc:
            # The watchdog being unreachable is itself the signal it watches for;
            # log it but keep the runner alive.
            logger.warning("heartbeat ping failed: %s", exc)
