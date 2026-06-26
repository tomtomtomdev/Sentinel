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
