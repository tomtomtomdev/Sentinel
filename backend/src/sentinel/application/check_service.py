"""Probe use case (SPEC §3.2, §3.3, §3.9). Orchestrates the ports — load the
monitor, build a `ProbeRequest`, optionally inject an auth-source token (proactive
refresh), send it via `HttpProbe`, evaluate assertions (pure domain logic), then
assemble and persist a `CheckResult`. This service holds flow only; the business
rules live in `evaluate_assertions` and `domain.logic.auth`.

A transport failure surfaces as a `ProbeError` and is recorded as a failed
`CheckResult` carrying its `ErrorKind` — never re-raised as an API error
(SPEC §3.3). A successful request whose assertions fail is recorded with
`error=assertion`. When the monitor links an auth source, a response whose status
is in the source's `refresh_on_status` triggers exactly one reactive refresh + one
retry (no loops); a persistent 401 is one recorded failed check."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sentinel.application.alert_service import AlertService
from sentinel.application.auth_token_service import AuthTokenService
from sentinel.domain.entities import AuthSource, CheckResult, Monitor
from sentinel.domain.errors import NotFoundError, ProbeError
from sentinel.domain.logic.assertions import evaluate_assertions
from sentinel.domain.logic.auth import apply_injection
from sentinel.domain.logic.rollups import fold_results_into_rollup, hour_bucket
from sentinel.domain.logic.state import advance_state, initial_state, transition_between
from sentinel.domain.ports import (
    AuthSourceRepository,
    CheckResultRepository,
    CheckRollupRepository,
    Clock,
    EventBus,
    HttpProbe,
    MonitorRepository,
    MonitorStateRepository,
)
from sentinel.domain.value_objects import (
    AssertionResult,
    CheckCompleted,
    ErrorKind,
    ProbeRequest,
    ProbeResponse,
    StateTransition,
)


class CheckService:
    def __init__(
        self,
        *,
        monitors: MonitorRepository,
        results: CheckResultRepository,
        probe: HttpProbe,
        clock: Clock,
        states: MonitorStateRepository | None = None,
        rollups: CheckRollupRepository | None = None,
        events: EventBus | None = None,
        alerts: AlertService | None = None,
        auth_sources: AuthSourceRepository | None = None,
        auth: AuthTokenService | None = None,
    ) -> None:
        self._monitors = monitors
        self._results = results
        self._probe = probe
        self._clock = clock
        self._states = states
        self._rollups = rollups
        self._events = events
        self._alerts = alerts
        self._auth_sources = auth_sources
        self._auth = auth

    async def run_check(self, monitor_id: UUID) -> CheckResult:
        monitor = await self._monitors.get(monitor_id)
        if monitor is None:
            raise NotFoundError(f"monitor {monitor_id} not found")

        result = await self._probe_and_record(monitor)
        transition = await self._advance_state(monitor, result)
        await self._advance_rollup(monitor, result)
        await self._publish_events(result, transition)
        await self._maybe_alert(monitor, result, transition)
        return result

    async def _probe_and_record(self, monitor: Monitor) -> CheckResult:
        source = await self._load_auth_source(monitor)
        started_at = self._clock.now()
        base_request = _to_probe_request(monitor)

        request, did_refresh = await self._inject(source, base_request, started_at)
        try:
            response = await self._send(monitor, request)
            response = await self._maybe_reactive_retry(
                monitor, source, base_request, response, did_refresh
            )
        except ProbeError as exc:
            return await self._record(monitor, started_at, success=False, error=exc.kind)

        finished_at = self._clock.now()
        assertion_results = evaluate_assertions(response, monitor.assertions, finished_at)
        success = all(r.passed for r in assertion_results)
        return await self._record(
            monitor,
            started_at,
            success=success,
            error=None if success else ErrorKind.ASSERTION,
            response=response,
            assertion_results=assertion_results,
            finished_at=finished_at,
        )

    async def _advance_state(self, monitor: Monitor, result: CheckResult) -> StateTransition | None:
        """Fold the result into the monitor's persisted `MonitorState` (SPEC §3.8)
        and return the confirmed `StateTransition`, if any. Every check bumps the
        counters + `last_check_at`; `status`/`since` flip only on a threshold
        crossing. Returns `None` (no transition) when nothing flipped, or when no
        state repository is wired (e.g. a manual-check path without state). The
        transition is published as a `status_changed` event by `_publish_events`
        (S8); S9 turns the same transition into an alert."""
        if self._states is None:
            return None
        current = await self._states.get(monitor.id) or initial_state(
            monitor.id, result.finished_at
        )
        updated = advance_state(
            current,
            result,
            failure_threshold=monitor.failure_threshold,
            recovery_threshold=monitor.recovery_threshold,
        )
        await self._states.save(updated)
        return transition_between(current, updated)

    async def _publish_events(
        self, result: CheckResult, transition: StateTransition | None
    ) -> None:
        """Push live events to connected SSE clients (SPEC §3.6). A `check_completed`
        fires for every recorded check; a `status_changed` (the `StateTransition`)
        only on a confirmed flip. No-op when no event bus is wired. Publishing never
        blocks or raises, so a slow/absent subscriber can't affect the check."""
        if self._events is None:
            return
        await self._events.publish(
            CheckCompleted(
                monitor_id=result.monitor_id,
                at=result.finished_at,
                success=result.success,
                status_code=result.status_code,
                latency_ms=result.latency_ms,
                error=result.error,
            )
        )
        if transition is not None:
            await self._events.publish(transition)

    async def _maybe_alert(
        self, monitor: Monitor, result: CheckResult, transition: StateTransition | None
    ) -> None:
        """Turn a confirmed transition into alerts (SPEC §3.7). No-op when no alert
        service is wired (e.g. the manual-check path) or when the check confirmed no
        transition; the `AlertService` runs `should_notify` and fans out to enabled
        channels. `result.error` is passed as the last error for the payload."""
        if self._alerts is None:
            return
        await self._alerts.maybe_notify(monitor, transition, last_error=result.error)

    async def _advance_rollup(self, monitor: Monitor, result: CheckResult) -> None:
        """Recompute the result's hour-bucket `CheckRollup` from raw and upsert it
        (SPEC §3.5, §6). Recomputing the whole bucket from its raw rows keeps the
        fold idempotent — a replayed check never double-counts — and the raw rows are
        always present (the check just landed, well inside the raw-retention window).
        No-op when no rollup repository is wired (e.g. the manual-check path)."""
        if self._rollups is None:
            return
        bucket = hour_bucket(result.finished_at)
        bucket_results = await self._results.list_for_monitor(
            monitor.id, since=bucket, until=bucket + timedelta(hours=1), limit=None
        )
        existing = await self._rollups.get(monitor.id, bucket)
        await self._rollups.save(fold_results_into_rollup(existing, bucket_results))

    async def _load_auth_source(self, monitor: Monitor) -> AuthSource | None:
        if monitor.auth_source_id is None or self._auth_sources is None or self._auth is None:
            return None
        return await self._auth_sources.get(monitor.auth_source_id)

    async def _inject(
        self, source: AuthSource | None, request: ProbeRequest, now: datetime
    ) -> tuple[ProbeRequest, bool]:
        """Proactively resolve+inject the token. Returns the request to send and
        whether a refresh happened (so the reactive path doesn't refresh twice)."""
        if source is None or self._auth is None:
            return request, False
        plan, did_refresh = await self._auth.ensure_fresh(source, now)
        return (apply_injection(request, plan) if plan is not None else request), did_refresh

    async def _maybe_reactive_retry(
        self,
        monitor: Monitor,
        source: AuthSource | None,
        base_request: ProbeRequest,
        response: ProbeResponse,
        did_refresh: bool,
    ) -> ProbeResponse:
        """If the response status is in the source's `refresh_on_status` and we
        haven't already refreshed this cycle, refresh once and retry the probe once."""
        if (
            source is None
            or self._auth is None
            or did_refresh
            or response.status_code not in source.refresh_on_status
        ):
            return response
        plan = await self._auth.force_refresh(source, self._clock.now())
        retry = apply_injection(base_request, plan) if plan is not None else base_request
        return await self._send(monitor, retry)

    async def _send(self, monitor: Monitor, request: ProbeRequest) -> ProbeResponse:
        return await self._probe.send(
            request,
            timeout_seconds=monitor.timeout_seconds,
            follow_redirects=monitor.follow_redirects,
        )

    async def _record(
        self,
        monitor: Monitor,
        started_at: datetime,
        *,
        success: bool,
        error: ErrorKind | None,
        response: ProbeResponse | None = None,
        assertion_results: list[AssertionResult] | None = None,
        finished_at: datetime | None = None,
    ) -> CheckResult:
        return await self._results.add(
            CheckResult(
                monitor_id=monitor.id,
                started_at=started_at,
                finished_at=finished_at or self._clock.now(),
                success=success,
                status_code=response.status_code if response else None,
                latency_ms=response.latency_ms if response else None,
                response_size_bytes=response.response_size_bytes if response else None,
                cert_expires_at=response.cert_expires_at if response else None,
                error=error,
                assertion_results=assertion_results or [],
            )
        )


def _to_probe_request(monitor: Monitor) -> ProbeRequest:
    """Map a monitor to the request to issue. Auth-source token injection (S5b) and
    the SSRF guard (S10) wrap this; it carries the monitor's own
    method/url/headers/body verbatim. The injected token is never persisted in a
    `CheckResult` (which stores no request/body sample)."""
    return ProbeRequest(
        method=monitor.method,
        url=monitor.url,
        headers=dict(monitor.headers),
        query_params=dict(monitor.query_params),
        body=monitor.body,
    )
