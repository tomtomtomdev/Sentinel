"""Postgres-backed `AuthSourceRepository` (SPEC §3.9). Maps between the domain
`AuthSource` and the `AuthSourceRow` table; stamps audit timestamps via the
injected `Clock`, exactly as the in-memory fake does.

Credentials are encrypted at rest via the injected `SecretBox` (SPEC §6): the
request body (login credentials), secret-bearing request headers, and the oauth
`client_secret`/`username`/`password` are ciphertext in the row and plaintext on
the entity. Encryption happens here on write and decryption here on read, keeping
the domain/application layers crypto-free (PLAN D18)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel.domain.entities import AuthSource
from sentinel.domain.ports import Clock, SecretBox
from sentinel.domain.value_objects import (
    AuthSourceMode,
    ClientAuth,
    ExpiryKind,
    ExpirySpec,
    ExtractorKind,
    HttpMethod,
    Injection,
    InjectionTarget,
    OAuthConfig,
    ProbeRequest,
    TokenExtractor,
)
from sentinel.infrastructure.db.models import AuthSourceRow
from sentinel.infrastructure.db.secret_mapping import (
    decrypt_secret_headers,
    decrypt_value,
    encrypt_secret_headers,
    encrypt_value,
)


def _request_to_json(req: ProbeRequest, box: SecretBox) -> dict[str, Any]:
    return {
        "method": req.method.value,
        "url": req.url,
        "headers": encrypt_secret_headers(req.headers, box),
        "query_params": dict(req.query_params),
        "body": encrypt_value(req.body, box) if req.body else None,
    }


def _request_from_json(data: dict[str, Any], box: SecretBox) -> ProbeRequest:
    body = data.get("body")
    return ProbeRequest(
        method=HttpMethod(data["method"]),
        url=data["url"],
        headers=decrypt_secret_headers(data.get("headers", {}), box),
        query_params=dict(data.get("query_params", {})),
        body=decrypt_value(body, box) if body else None,
    )


def _oauth_to_json(oauth: OAuthConfig | None, box: SecretBox) -> dict[str, Any] | None:
    if oauth is None:
        return None
    return {
        "token_url": oauth.token_url,
        "client_id": oauth.client_id,
        "client_secret": encrypt_value(oauth.client_secret, box) if oauth.client_secret else None,
        "scope": oauth.scope,
        "client_auth": oauth.client_auth.value,
        "username": encrypt_value(oauth.username, box) if oauth.username else None,
        "password": encrypt_value(oauth.password, box) if oauth.password else None,
    }


def _oauth_from_json(data: dict[str, Any] | None, box: SecretBox) -> OAuthConfig | None:
    if data is None:
        return None
    secret, user, pw = data.get("client_secret"), data.get("username"), data.get("password")
    return OAuthConfig(
        token_url=data["token_url"],
        client_id=data["client_id"],
        client_secret=decrypt_value(secret, box) if secret else None,
        scope=data.get("scope"),
        client_auth=ClientAuth(data["client_auth"]),
        username=decrypt_value(user, box) if user else None,
        password=decrypt_value(pw, box) if pw else None,
    )


def _extractor_to_json(extractor: TokenExtractor) -> dict[str, Any]:
    return {"kind": extractor.kind.value, "expr": extractor.expr}


def _extractor_from_json(data: dict[str, Any]) -> TokenExtractor:
    return TokenExtractor(kind=ExtractorKind(data["kind"]), expr=data["expr"])


def _expiry_to_json(expiry: ExpirySpec | None) -> dict[str, Any] | None:
    if expiry is None:
        return None
    return {"kind": expiry.kind.value, "value": expiry.value}


def _expiry_from_json(data: dict[str, Any] | None) -> ExpirySpec | None:
    if data is None:
        return None
    return ExpirySpec(kind=ExpiryKind(data["kind"]), value=data["value"])


def _injection_to_json(injection: Injection) -> dict[str, Any]:
    return {
        "target": injection.target.value,
        "name": injection.name,
        "value_template": injection.value_template,
    }


def _injection_from_json(data: dict[str, Any]) -> Injection:
    return Injection(
        target=InjectionTarget(data["target"]),
        name=data["name"],
        value_template=data["value_template"],
    )


def _to_row(
    source: AuthSource, *, secret_box: SecretBox, created_at: datetime, updated_at: datetime
) -> AuthSourceRow:
    return AuthSourceRow(
        id=source.id,
        name=source.name,
        mode=source.mode.value,
        request=_request_to_json(source.request, secret_box),
        oauth=_oauth_to_json(source.oauth, secret_box),
        extractor=_extractor_to_json(source.extractor),
        expiry=_expiry_to_json(source.expiry),
        token_type=source.token_type,
        injection=_injection_to_json(source.injection),
        refresh_before_expiry_seconds=source.refresh_before_expiry_seconds,
        refresh_on_status=list(source.refresh_on_status),
        enabled=source.enabled,
        created_at=created_at,
        updated_at=updated_at,
    )


def _to_entity(row: AuthSourceRow, *, secret_box: SecretBox) -> AuthSource:
    return AuthSource(
        id=row.id,
        name=row.name,
        mode=AuthSourceMode(row.mode),
        request=_request_from_json(row.request, secret_box),
        oauth=_oauth_from_json(row.oauth, secret_box),
        extractor=_extractor_from_json(row.extractor),
        expiry=_expiry_from_json(row.expiry),
        token_type=row.token_type,
        injection=_injection_from_json(row.injection),
        refresh_before_expiry_seconds=row.refresh_before_expiry_seconds,
        refresh_on_status=list(row.refresh_on_status),
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_MUTABLE_FIELDS = (
    "name",
    "mode",
    "request",
    "oauth",
    "extractor",
    "expiry",
    "token_type",
    "injection",
    "refresh_before_expiry_seconds",
    "refresh_on_status",
    "enabled",
    "updated_at",
)


class SqlAuthSourceRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        secret_box: SecretBox,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._secret_box = secret_box

    async def add(self, auth_source: AuthSource) -> AuthSource:
        now = self._clock.now()
        row = _to_row(
            auth_source,
            secret_box=self._secret_box,
            created_at=auth_source.created_at or now,
            updated_at=now,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_entity(row, secret_box=self._secret_box)

    async def get(self, auth_source_id: UUID) -> AuthSource | None:
        async with self._session_factory() as session:
            row = await session.get(AuthSourceRow, auth_source_id)
            return _to_entity(row, secret_box=self._secret_box) if row is not None else None

    async def list(self) -> list[AuthSource]:
        async with self._session_factory() as session:
            result = await session.execute(select(AuthSourceRow))
            return [_to_entity(row, secret_box=self._secret_box) for row in result.scalars().all()]

    async def update(self, auth_source: AuthSource) -> AuthSource:
        async with self._session_factory() as session:
            row = await session.get(AuthSourceRow, auth_source.id)
            if row is None:
                raise LookupError(auth_source.id)
            new = _to_row(
                auth_source,
                secret_box=self._secret_box,
                created_at=row.created_at,
                updated_at=self._clock.now(),
            )
            for field_name in _MUTABLE_FIELDS:
                setattr(row, field_name, getattr(new, field_name))
            await session.commit()
            await session.refresh(row)
            return _to_entity(row, secret_box=self._secret_box)

    async def delete(self, auth_source_id: UUID) -> bool:
        async with self._session_factory() as session:
            row = await session.get(AuthSourceRow, auth_source_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True
