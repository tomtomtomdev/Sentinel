"""Auth-source CRUD + manual-refresh routes (SPEC §3.9, §5). Thin transport
layer: parse DTO → delegate to the use case → serialize a credential-redacted
response. The refresh endpoint returns token metadata only — never the token
value. Domain errors raised here become the SPEC §5 envelope via the registered
handlers."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from sentinel.application.auth_source_service import AuthSourceService
from sentinel.application.auth_token_service import AuthTokenService
from sentinel.domain.ports import Clock, TokenStore
from sentinel.interface.api.deps import (
    get_auth_source_service,
    get_auth_token_service,
    get_clock,
    get_token_store,
)
from sentinel.interface.api.schemas import (
    AuthSourceCreate,
    AuthSourceResponse,
    AuthSourceUpdate,
    TokenStateSummary,
)

router = APIRouter(prefix="/auth-sources", tags=["auth-sources"])

ServiceDep = Annotated[AuthSourceService, Depends(get_auth_source_service)]
TokenServiceDep = Annotated[AuthTokenService, Depends(get_auth_token_service)]
TokenStoreDep = Annotated[TokenStore, Depends(get_token_store)]
ClockDep = Annotated[Clock, Depends(get_clock)]


@router.post("", response_model=AuthSourceResponse, status_code=201)
async def create_auth_source(payload: AuthSourceCreate, service: ServiceDep) -> AuthSourceResponse:
    created = await service.create(payload.to_entity())
    return AuthSourceResponse.from_entity(created)


@router.get("", response_model=list[AuthSourceResponse])
async def list_auth_sources(service: ServiceDep) -> list[AuthSourceResponse]:
    sources = await service.list()
    return [AuthSourceResponse.from_entity(s) for s in sources]


@router.get("/{auth_source_id}", response_model=AuthSourceResponse)
async def get_auth_source(
    auth_source_id: UUID, service: ServiceDep, tokens: TokenStoreDep, clock: ClockDep
) -> AuthSourceResponse:
    source = await service.get(auth_source_id)
    state = await tokens.load(auth_source_id)
    return AuthSourceResponse.from_entity(source, TokenStateSummary.from_state(state, clock.now()))


@router.patch("/{auth_source_id}", response_model=AuthSourceResponse)
async def update_auth_source(
    auth_source_id: UUID, payload: AuthSourceUpdate, service: ServiceDep
) -> AuthSourceResponse:
    existing = await service.get(auth_source_id)
    updated = await service.update(payload.apply_to(existing))
    return AuthSourceResponse.from_entity(updated)


@router.delete("/{auth_source_id}", status_code=204)
async def delete_auth_source(auth_source_id: UUID, service: ServiceDep) -> None:
    await service.delete(auth_source_id)


@router.post("/{auth_source_id}/refresh", response_model=TokenStateSummary)
async def refresh_auth_source(
    auth_source_id: UUID, service: TokenServiceDep, clock: ClockDep
) -> TokenStateSummary:
    """Regenerate the token now and return metadata only (SPEC §3.9). A transport
    or extraction failure is recorded as `status=error` (200), never raised."""
    state = await service.refresh(auth_source_id)
    return TokenStateSummary.from_state(state, clock.now())
