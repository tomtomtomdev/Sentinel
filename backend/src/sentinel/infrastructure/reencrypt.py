"""Offline re-encryption pass (S15, SPEC §6, PLAN D40).

After `SECRET_KEY` is rotated (a fresh key prepended to the ring), existing
ciphertext stays encrypted under whatever key wrote it — Sentinel never
auto-re-encrypts data at rest. This command walks every secret-bearing column and
rotates each ciphertext onto the ring's *first* key via `SecretBox.rotate`
(`MultiFernet.rotate`: decrypt-with-any → encrypt-with-first, never materializing
plaintext). Once it completes, nothing depends on the old key, so the operator can
drop it from `SECRET_KEY` on the next redeploy — the step the key-rotation runbook
otherwise cannot make safe (D39).

The set of secret columns mirrors the repositories' own at-rest mapping —
`monitor_repository` (secret headers), `auth_source_repository` (login body,
secret headers, oauth secrets), `token_store` (token/refresh_token) and
`alert_channel_repository` (secret config). If a new secret field is ever added
there, add it here too. Run it from the CLI: `python -m sentinel.infrastructure.reencrypt`
(or `just reencrypt`), pointed at the same `DATABASE_URL`/`SECRET_KEY` as the app,
while the app is quiescent enough that no secret is written under the old key
mid-pass.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel.config import get_settings
from sentinel.domain.logic.redaction import is_secret_config_key, is_secret_header
from sentinel.domain.ports import SecretBox
from sentinel.infrastructure.db.engine import create_engine, create_session_factory
from sentinel.infrastructure.db.models import (
    AlertChannelRow,
    AuthSourceRow,
    MonitorRow,
    TokenStateRow,
)
from sentinel.infrastructure.db.secret_mapping import (
    rotate_secret_config,
    rotate_secret_headers,
    rotate_value,
)
from sentinel.infrastructure.logging_config import configure_logging
from sentinel.infrastructure.secrets import FernetSecretBox

logger = logging.getLogger("sentinel.reencrypt")


@dataclass(frozen=True)
class ReEncryptReport:
    """Rows re-encrypted per secret-bearing table (a row counts only if it
    actually carried a secret value). Secret-free — safe to log."""

    monitors: int
    auth_sources: int
    token_states: int
    alert_channels: int


# --- auth-source payload rotation (mirrors auth_source_repository._request_to_json /
# _oauth_to_json — the source of truth for which sub-fields are secret) -----------


def rotate_auth_request(request: dict[str, Any], box: SecretBox) -> dict[str, Any]:
    """Rotate an auth source's stored login `request`: its secret headers and the
    credential `body`. Other fields (method/url/query_params) are never ciphertext."""
    rotated = dict(request)
    rotated["headers"] = rotate_secret_headers(request.get("headers", {}), box)
    body = request.get("body")
    if body:
        rotated["body"] = rotate_value(body, box)
    return rotated


def rotate_auth_oauth(oauth: dict[str, Any], box: SecretBox) -> dict[str, Any]:
    """Rotate an auth source's oauth secrets (client_secret/username/password);
    every other field is stored in the clear."""
    rotated = dict(oauth)
    for field in ("client_secret", "username", "password"):
        value = oauth.get(field)
        if value:
            rotated[field] = rotate_value(value, box)
    return rotated


def _request_has_secret(request: dict[str, Any]) -> bool:
    headers = request.get("headers", {})
    return bool(request.get("body")) or any(is_secret_header(name) for name in headers)


def _oauth_has_secret(oauth: dict[str, Any]) -> bool:
    return any(oauth.get(field) for field in ("client_secret", "username", "password"))


class ReEncryptor:
    """Rotates every stored ciphertext onto the current first key. Each table is
    handled in its own transaction; re-running is safe (rotation is idempotent in
    effect — the plaintext is preserved, only the key changes)."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], secret_box: SecretBox
    ) -> None:
        self._session_factory = session_factory
        self._box = secret_box

    async def run(self) -> ReEncryptReport:
        return ReEncryptReport(
            monitors=await self._rotate_monitors(),
            auth_sources=await self._rotate_auth_sources(),
            token_states=await self._rotate_token_states(),
            alert_channels=await self._rotate_alert_channels(),
        )

    async def _rotate_monitors(self) -> int:
        rows = 0
        async with self._session_factory() as session:
            for row in (await session.execute(select(MonitorRow))).scalars().all():
                if not any(is_secret_header(name) for name in row.headers):
                    continue
                row.headers = rotate_secret_headers(row.headers, self._box)
                rows += 1
            await session.commit()
        return rows

    async def _rotate_auth_sources(self) -> int:
        rows = 0
        async with self._session_factory() as session:
            for row in (await session.execute(select(AuthSourceRow))).scalars().all():
                oauth_secret = row.oauth is not None and _oauth_has_secret(row.oauth)
                if not (_request_has_secret(row.request) or oauth_secret):
                    continue
                row.request = rotate_auth_request(row.request, self._box)
                if row.oauth is not None:
                    row.oauth = rotate_auth_oauth(row.oauth, self._box)
                rows += 1
            await session.commit()
        return rows

    async def _rotate_token_states(self) -> int:
        rows = 0
        async with self._session_factory() as session:
            for row in (await session.execute(select(TokenStateRow))).scalars().all():
                # `token` is NOT NULL, so every cached token is a secret to rotate.
                row.token = rotate_value(row.token, self._box)
                if row.refresh_token is not None:
                    row.refresh_token = rotate_value(row.refresh_token, self._box)
                rows += 1
            await session.commit()
        return rows

    async def _rotate_alert_channels(self) -> int:
        rows = 0
        async with self._session_factory() as session:
            for row in (await session.execute(select(AlertChannelRow))).scalars().all():
                if not any(
                    is_secret_config_key(key) and isinstance(value, str)
                    for key, value in row.config.items()
                ):
                    continue
                row.config = rotate_secret_config(row.config, self._box)
                rows += 1
            await session.commit()
        return rows


async def _run() -> ReEncryptReport:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        reencryptor = ReEncryptor(
            create_session_factory(engine), FernetSecretBox(settings.secret_key_ring())
        )
        return await reencryptor.run()
    finally:
        await engine.dispose()


def main() -> None:
    configure_logging()
    report = asyncio.run(_run())
    logger.info(
        "re-encryption complete",
        extra={
            "monitors": report.monitors,
            "auth_sources": report.auth_sources,
            "token_states": report.token_states,
            "alert_channels": report.alert_channels,
        },
    )


if __name__ == "__main__":
    main()
