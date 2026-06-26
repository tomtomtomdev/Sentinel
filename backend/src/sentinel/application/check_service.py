"""Probe use case (SPEC §3.2, §3.3). Orchestrates the ports — load the monitor,
build a `ProbeRequest`, send it via `HttpProbe`, evaluate assertions (pure domain
logic), then assemble and persist a `CheckResult`. This service holds flow only;
the business rules live in `evaluate_assertions`.

A transport failure surfaces as a `ProbeError` and is recorded as a failed
`CheckResult` carrying its `ErrorKind` — never re-raised as an API error
(SPEC §3.3). A successful request whose assertions fail is recorded with
`error=assertion`."""

from __future__ import annotations

from uuid import UUID

from sentinel.domain.entities import CheckResult, Monitor
from sentinel.domain.errors import NotFoundError, ProbeError
from sentinel.domain.logic.assertions import evaluate_assertions
from sentinel.domain.ports import CheckResultRepository, Clock, HttpProbe, MonitorRepository
from sentinel.domain.value_objects import ErrorKind, ProbeRequest


class CheckService:
    def __init__(
        self,
        *,
        monitors: MonitorRepository,
        results: CheckResultRepository,
        probe: HttpProbe,
        clock: Clock,
    ) -> None:
        self._monitors = monitors
        self._results = results
        self._probe = probe
        self._clock = clock

    async def run_check(self, monitor_id: UUID) -> CheckResult:
        monitor = await self._monitors.get(monitor_id)
        if monitor is None:
            raise NotFoundError(f"monitor {monitor_id} not found")

        started_at = self._clock.now()
        try:
            response = await self._probe.send(
                _to_probe_request(monitor),
                timeout_seconds=monitor.timeout_seconds,
                follow_redirects=monitor.follow_redirects,
            )
        except ProbeError as exc:
            return await self._results.add(
                CheckResult(
                    monitor_id=monitor.id,
                    started_at=started_at,
                    finished_at=self._clock.now(),
                    success=False,
                    error=exc.kind,
                )
            )

        finished_at = self._clock.now()
        assertion_results = evaluate_assertions(response, monitor.assertions, finished_at)
        success = all(r.passed for r in assertion_results)
        return await self._results.add(
            CheckResult(
                monitor_id=monitor.id,
                started_at=started_at,
                finished_at=finished_at,
                success=success,
                status_code=response.status_code,
                latency_ms=response.latency_ms,
                response_size_bytes=response.response_size_bytes,
                cert_expires_at=response.cert_expires_at,
                error=None if success else ErrorKind.ASSERTION,
                assertion_results=assertion_results,
            )
        )


def _to_probe_request(monitor: Monitor) -> ProbeRequest:
    """Map a monitor to the request to issue. Auth-source token injection (S5b) and
    the SSRF guard (S10) will wrap this; for now it carries the monitor's own
    method/url/headers/body verbatim."""
    return ProbeRequest(
        method=monitor.method,
        url=monitor.url,
        headers=dict(monitor.headers),
        query_params=dict(monitor.query_params),
        body=monitor.body,
    )
