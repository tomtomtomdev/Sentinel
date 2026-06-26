"""Import routes (SPEC §3.1). A curl command or a Postman v2.1 collection is
parsed into reviewable drafts and returned; nothing is persisted (the client saves
drafts via POST /monitors). Parsing is a pure domain function, so the route calls
it directly — there is no I/O to orchestrate, hence no application use case. The
Postman route only reads the upload and decodes JSON; the file's contents are
untrusted data, never executed."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from sentinel.domain.errors import ValidationError
from sentinel.domain.logic.curl_import import parse_curl
from sentinel.domain.logic.postman_import import parse_postman
from sentinel.interface.api.schemas import (
    CurlImportRequest,
    ImportResponse,
    MonitorDraftResponse,
)

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/curl", response_model=ImportResponse)
async def import_curl(payload: CurlImportRequest) -> ImportResponse:
    draft = parse_curl(payload.command)
    return ImportResponse(drafts=[MonitorDraftResponse.from_draft(draft)])


@router.post("/postman", response_model=ImportResponse)
async def import_postman(file: Annotated[UploadFile, File()]) -> ImportResponse:
    raw = await file.read()
    try:
        collection = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError("uploaded file is not valid JSON") from exc
    if not isinstance(collection, dict):
        raise ValidationError("Postman collection must be a JSON object")
    drafts = parse_postman(collection)
    return ImportResponse(drafts=[MonitorDraftResponse.from_draft(d) for d in drafts])
