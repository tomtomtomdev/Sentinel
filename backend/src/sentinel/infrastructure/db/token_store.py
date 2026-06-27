"""Postgres-backed `TokenStore` (SPEC §3.9). Persists the single cached
`TokenState` per auth source — `save` is an upsert keyed by `auth_source_id`, so
one row serves all monitors linked to the source. The `token` and `refresh_token`
are encrypted at rest via the injected `SecretBox` (SPEC §6) and decrypted on
`load`, so the entity carries plaintext and the row never does."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel.domain.entities import TokenState
from sentinel.domain.ports import SecretBox
from sentinel.infrastructure.db.models import TokenStateRow
from sentinel.infrastructure.db.secret_mapping import decrypt_value, encrypt_value


class SqlTokenStore:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], secret_box: SecretBox
    ) -> None:
        self._session_factory = session_factory
        self._secret_box = secret_box

    async def load(self, auth_source_id: UUID) -> TokenState | None:
        async with self._session_factory() as session:
            row = await session.get(TokenStateRow, auth_source_id)
            if row is None:
                return None
            return TokenState(
                auth_source_id=row.auth_source_id,
                token=decrypt_value(row.token, self._secret_box),
                token_type=row.token_type,
                obtained_at=row.obtained_at,
                expires_at=row.expires_at,
                refresh_token=(
                    decrypt_value(row.refresh_token, self._secret_box)
                    if row.refresh_token is not None
                    else None
                ),
                last_refresh_error=row.last_refresh_error,
            )

    async def save(self, token_state: TokenState) -> TokenState:
        token = encrypt_value(token_state.token, self._secret_box)
        refresh = (
            encrypt_value(token_state.refresh_token, self._secret_box)
            if token_state.refresh_token is not None
            else None
        )
        async with self._session_factory() as session:
            row = await session.get(TokenStateRow, token_state.auth_source_id)
            if row is None:
                row = TokenStateRow(
                    auth_source_id=token_state.auth_source_id,
                    token=token,
                    token_type=token_state.token_type,
                    obtained_at=token_state.obtained_at,
                )
                session.add(row)
            row.token = token
            row.refresh_token = refresh
            row.token_type = token_state.token_type
            row.obtained_at = token_state.obtained_at
            row.expires_at = token_state.expires_at
            row.last_refresh_error = token_state.last_refresh_error
            await session.commit()
        return token_state
