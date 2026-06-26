from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class BodyKind(StrEnum):
    NONE = "none"
    RAW = "raw"
    JSON = "json"
    FORM = "form"


class AuthType(StrEnum):
    NONE = "none"
    BASIC = "basic"
    BEARER = "bearer"


@dataclass(frozen=True)
class Auth:
    """Inline monitor auth. `secret_ref` points at the encrypted secret (S5a);
    the secret value itself never lives on the entity."""

    type: AuthType
    secret_ref: str | None = None


@dataclass(frozen=True)
class Assertion:
    """A single check predicate (SPEC §3.4). Carried as type + params here;
    per-type validation and evaluation arrive with the engine in S5."""

    type: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class MonitorDraft:
    """An unsaved, reviewable monitor produced by an importer (SPEC §3.1, §4).
    Deliberately carries no invariants: a draft may be incomplete and is meant to
    be edited before being saved via the create endpoint. `warnings` surface
    anything the importer could not faithfully represent."""

    name: str
    url: str
    method: HttpMethod = HttpMethod.GET
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    body_kind: BodyKind = BodyKind.NONE
    follow_redirects: bool = False
    assertions: list[Assertion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
