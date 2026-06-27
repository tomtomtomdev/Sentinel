"""Token-refresh use case (SPEC §3.9). Orchestrates the ports to (re)generate an
auth source's cached token: build the token request for the source's grant mode,
probe it via `HttpProbe`, extract the token with the pure `extract_token`, and
persist the single cached `TokenState` (encrypted at rest by the store).

This service holds flow only; the business rules (request building, extraction,
the refresh decision) are the pure functions in `domain.logic.auth`. A failed
refresh (transport error or extraction failure) is **recorded** as
`TokenState.last_refresh_error` and never raised — a previously valid token is
preserved so a transient IdP blip doesn't drop a working token. The single-flight
lock and the probe-pipeline's proactive/reactive refresh build on this in S5b.4."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sentinel.domain.entities import AuthSource, TokenState
from sentinel.domain.errors import NotFoundError, ProbeError, TokenExtractionError
from sentinel.domain.logic.auth import (
    build_oauth_token_request,
    build_token_request,
    extract_token,
)
from sentinel.domain.ports import AuthSourceRepository, Clock, HttpProbe, TokenStore
from sentinel.domain.value_objects import AuthSourceMode, OAuthGrant, ProbeRequest

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

    async def current(self, auth_source_id: UUID) -> TokenState | None:
        return await self._tokens.load(auth_source_id)

    async def refresh(self, auth_source_id: UUID) -> TokenState:
        source = await self._sources.get(auth_source_id)
        if source is None:
            raise NotFoundError(f"auth source {auth_source_id} not found")
        existing = await self._tokens.load(auth_source_id)
        now = self._clock.now()
        try:
            request = self._build_request(source, existing)
            response = await self._probe.send(
                request,
                timeout_seconds=TOKEN_REQUEST_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
            token = extract_token(response, source.extractor, source.expiry, now)
        except (ProbeError, TokenExtractionError) as exc:
            return await self._tokens.save(_failed_state(source, existing, now, str(exc)))

        return await self._tokens.save(
            TokenState(
                auth_source_id=source.id,
                token=token.value,
                token_type=source.token_type,
                obtained_at=now,
                expires_at=token.expires_at,
                refresh_token=token.refresh_token
                or (existing.refresh_token if existing else None),
                last_refresh_error=None,
            )
        )

    def _build_request(self, source: AuthSource, existing: TokenState | None) -> ProbeRequest:
        if source.mode is AuthSourceMode.CUSTOM:
            return build_token_request(source)
        oauth = source.oauth
        if oauth is None:  # the entity invariant guarantees this; guard for safety
            raise TokenExtractionError(f"{source.mode.value} auth source missing oauth config")
        if source.mode is AuthSourceMode.OAUTH2_CLIENT_CREDENTIALS:
            return build_oauth_token_request(oauth, OAuthGrant.CLIENT_CREDENTIALS)
        if source.mode is AuthSourceMode.OAUTH2_PASSWORD:
            return build_oauth_token_request(oauth, OAuthGrant.PASSWORD)
        # OAUTH2_REFRESH — reuse the stored refresh token.
        refresh = existing.refresh_token if existing else None
        if not refresh:
            raise TokenExtractionError("oauth2_refresh source has no stored refresh_token")
        return build_oauth_token_request(oauth, OAuthGrant.REFRESH_TOKEN, refresh_token=refresh)


def _failed_state(
    source: AuthSource, existing: TokenState | None, now: datetime, error: str
) -> TokenState:
    """Record the failure without dropping a still-usable token: keep the existing
    token/expiry and only stamp `last_refresh_error`; if there was no token, persist
    an empty one carrying the error."""
    if existing is not None:
        return replace(existing, last_refresh_error=error)
    return TokenState(
        auth_source_id=source.id,
        token="",
        token_type=source.token_type,
        obtained_at=now,
        last_refresh_error=error,
    )
