"""Token use case (SPEC §3.9). Owns everything about an auth source's cached
token: the proactive refresh decision, the reactive (post-401) refresh, manual
refresh, OAuth2 refresh-token reuse with fallback to a full login, and a
per-source single-flight lock so a herd of due monitors triggers one login.

Flow only — the business rules (request building, extraction, the refresh
decision) are the pure functions in `domain.logic.auth`. A failed refresh
(transport error or extraction failure) is **recorded** as
`TokenState.last_refresh_error` and never raised; a previously valid token is
preserved so a transient IdP blip doesn't drop a working token. Tokens are
decrypted by the `TokenStore` and live only in memory / the outbound request —
this is the decrypt-at-use case from PLAN D18."""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID

from sentinel.domain.entities import AuthSource, TokenState
from sentinel.domain.errors import NotFoundError, ProbeError, TokenExtractionError
from sentinel.domain.logic.auth import (
    build_oauth_token_request,
    build_token_request,
    extract_token,
    resolve_auth,
)
from sentinel.domain.ports import AuthSourceRepository, Clock, HttpProbe, TokenStore
from sentinel.domain.value_objects import (
    AuthSourceMode,
    InjectionPlan,
    OAuthGrant,
    ProbeRequest,
    Token,
)

# Login/token endpoints have no per-source timeout in the model; use a generous
# default (a login can be slower than a health probe).
TOKEN_REQUEST_TIMEOUT_SECONDS = 30.0


class AuthTokenService:
    def __init__(
        self,
        *,
        sources: AuthSourceRepository,
        tokens: TokenStore,
        probe: HttpProbe,
        clock: Clock,
    ) -> None:
        self._sources = sources
        self._tokens = tokens
        self._probe = probe
        self._clock = clock
        self._locks: dict[UUID, asyncio.Lock] = {}

    async def current(self, auth_source_id: UUID) -> TokenState | None:
        return await self._tokens.load(auth_source_id)

    async def refresh(self, auth_source_id: UUID) -> TokenState:
        """Manual refresh (the API endpoint): always regenerate once, single-flighted."""
        async with self._lock_for(auth_source_id):
            return await self._refresh_unlocked(auth_source_id)

    async def ensure_fresh(
        self, source: AuthSource, now: datetime
    ) -> tuple[InjectionPlan | None, bool]:
        """Proactive: return an `InjectionPlan` for a valid token, refreshing under
        the per-source lock if needed. Double-checked so a herd of due monitors
        triggers one login. The bool is whether *this* check performed a refresh —
        the caller uses it to cap a check at one refresh (no reactive double-refresh)."""
        decision = resolve_auth(source, await self._tokens.load(source.id), now)
        if isinstance(decision, InjectionPlan):
            return decision, False
        async with self._lock_for(source.id):
            # A waiter ahead of us may have refreshed while we queued.
            decision = resolve_auth(source, await self._tokens.load(source.id), now)
            if isinstance(decision, InjectionPlan):
                return decision, False
            refreshed = await self._refresh_unlocked(source.id)
        return _plan_or_none(source, refreshed, now), True

    async def force_refresh(self, source: AuthSource, now: datetime) -> InjectionPlan | None:
        """Reactive: the token was rejected, so refresh once (single-flighted) and
        return a plan for the new token (or None if the refresh failed)."""
        async with self._lock_for(source.id):
            refreshed = await self._refresh_unlocked(source.id)
        return _plan_or_none(source, refreshed, now)

    async def _refresh_unlocked(self, auth_source_id: UUID) -> TokenState:
        source = await self._sources.get(auth_source_id)
        if source is None:
            raise NotFoundError(f"auth source {auth_source_id} not found")
        existing = await self._tokens.load(auth_source_id)
        now = self._clock.now()
        last_error = "no token grant available for this auth source"
        # Try each grant in order: OAuth refresh-token reuse first (when a refresh
        # token is cached), then the mode's primary grant as a fallback.
        for request in _grant_plan(source, existing):
            try:
                response = await self._probe.send(
                    request,
                    timeout_seconds=TOKEN_REQUEST_TIMEOUT_SECONDS,
                    follow_redirects=True,
                )
                token = extract_token(response, source.extractor, source.expiry, now)
            except (ProbeError, TokenExtractionError) as exc:
                last_error = str(exc)
                continue
            return await self._tokens.save(_success_state(source, token, existing, now))
        return await self._tokens.save(_failed_state(source, existing, now, last_error))

    def _lock_for(self, auth_source_id: UUID) -> asyncio.Lock:
        lock = self._locks.get(auth_source_id)
        if lock is None:  # safe in asyncio: no await between get and set
            lock = asyncio.Lock()
            self._locks[auth_source_id] = lock
        return lock


def _grant_plan(source: AuthSource, existing: TokenState | None) -> list[ProbeRequest]:
    """The ordered token requests to attempt. A cached refresh token is reused
    first (the `refresh_token` grant); the mode's primary grant follows as a
    fallback, satisfying SPEC §3.9 refresh-token-reuse-with-fallback."""
    if source.mode is AuthSourceMode.CUSTOM:
        return [build_token_request(source)]
    oauth = source.oauth
    if oauth is None:  # unreachable — the entity invariant requires oauth here
        return []
    requests: list[ProbeRequest] = []
    refresh_token = existing.refresh_token if existing else None
    if refresh_token:
        requests.append(
            build_oauth_token_request(oauth, OAuthGrant.REFRESH_TOKEN, refresh_token=refresh_token)
        )
    if source.mode is AuthSourceMode.OAUTH2_CLIENT_CREDENTIALS:
        requests.append(build_oauth_token_request(oauth, OAuthGrant.CLIENT_CREDENTIALS))
    elif source.mode is AuthSourceMode.OAUTH2_PASSWORD:
        requests.append(build_oauth_token_request(oauth, OAuthGrant.PASSWORD))
    # OAUTH2_REFRESH has only the refresh-token grant (added above when available).
    return requests


def _plan_or_none(source: AuthSource, state: TokenState, now: datetime) -> InjectionPlan | None:
    decision = resolve_auth(source, state, now)
    return decision if isinstance(decision, InjectionPlan) else None


def _success_state(
    source: AuthSource, token: Token, existing: TokenState | None, now: datetime
) -> TokenState:
    return TokenState(
        auth_source_id=source.id,
        token=token.value,
        token_type=source.token_type,
        obtained_at=now,
        expires_at=token.expires_at,
        # Keep the prior refresh token if this response didn't return a new one.
        refresh_token=token.refresh_token or (existing.refresh_token if existing else None),
        last_refresh_error=None,
    )


def _failed_state(
    source: AuthSource, existing: TokenState | None, now: datetime, error: str
) -> TokenState:
    """Record the failure without dropping a still-usable token: keep the existing
    token/expiry/refresh-token and only stamp `last_refresh_error`; if there was no
    token, persist an empty one carrying the error."""
    if existing is not None:
        return TokenState(
            auth_source_id=existing.auth_source_id,
            token=existing.token,
            token_type=existing.token_type,
            obtained_at=existing.obtained_at,
            expires_at=existing.expires_at,
            refresh_token=existing.refresh_token,
            last_refresh_error=error,
        )
    return TokenState(
        auth_source_id=source.id,
        token="",
        token_type=source.token_type,
        obtained_at=now,
        last_refresh_error=error,
    )
