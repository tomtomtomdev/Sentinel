"""Import routes (SPEC §3.1). A curl command is parsed into reviewable drafts and
returned; nothing is persisted (the client saves drafts via POST /monitors).
Parsing is a pure domain function, so the route calls it directly — there is no
I/O to orchestrate, hence no application use case."""

from __future__ import annotations

from fastapi import APIRouter

from sentinel.domain.logic.curl_import import parse_curl
from sentinel.interface.api.schemas import (
    CurlImportRequest,
    CurlImportResponse,
    MonitorDraftResponse,
)

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/curl", response_model=CurlImportResponse)
async def import_curl(payload: CurlImportRequest) -> CurlImportResponse:
    draft = parse_curl(payload.command)
    return CurlImportResponse(drafts=[MonitorDraftResponse.from_draft(draft)])
