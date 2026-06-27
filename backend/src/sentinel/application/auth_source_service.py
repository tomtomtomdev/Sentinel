"""Auth-source CRUD use case (SPEC §3.9). Orchestrates the `AuthSourceRepository`
port; it wires flow only — entity invariants live on `AuthSource`, timestamps are
stamped by the repository's injected `Clock`. Missing entities surface as a typed
`NotFoundError` the API maps to 404. Token refresh is a separate use case
(`AuthTokenService`)."""

from __future__ import annotations

from uuid import UUID

from sentinel.domain.entities import AuthSource
from sentinel.domain.errors import NotFoundError
from sentinel.domain.ports import AuthSourceRepository


class AuthSourceService:
    def __init__(self, repository: AuthSourceRepository) -> None:
        self._repository = repository

    async def create(self, auth_source: AuthSource) -> AuthSource:
        return await self._repository.add(auth_source)

    async def list(self) -> list[AuthSource]:
        return await self._repository.list()

    async def get(self, auth_source_id: UUID) -> AuthSource:
        source = await self._repository.get(auth_source_id)
        if source is None:
            raise NotFoundError(f"auth source {auth_source_id} not found")
        return source

    async def update(self, auth_source: AuthSource) -> AuthSource:
        try:
            return await self._repository.update(auth_source)
        except LookupError as exc:
            raise NotFoundError(f"auth source {auth_source.id} not found") from exc

    async def delete(self, auth_source_id: UUID) -> None:
        if not await self._repository.delete(auth_source_id):
            raise NotFoundError(f"auth source {auth_source_id} not found")
