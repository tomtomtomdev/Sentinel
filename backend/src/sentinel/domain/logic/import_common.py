"""Shared pure helpers for the importers (`parse_curl`, `parse_postman`). No I/O:
imported content is untrusted data, so these only inspect and reshape strings."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from sentinel.domain.value_objects import BodyKind, HttpMethod

_KNOWN_METHODS = {m.value for m in HttpMethod}
_FORM_BODY = re.compile(r"^[^=&\s]+=[^&]*(&[^=&\s]+=[^&]*)*$")


def coerce_method(
    method: str, warnings: list[str], *, default: HttpMethod = HttpMethod.GET
) -> HttpMethod:
    """Map a method string to an `HttpMethod`, warning and falling back to
    `default` when it is not one Sentinel can monitor."""
    upper = method.upper()
    if upper not in _KNOWN_METHODS:
        warnings.append(f"unsupported method '{method}', defaulting to {default.value}")
        return default
    return HttpMethod(upper)


def derive_name(method: HttpMethod, url: str) -> str:
    """A human-friendly default name: ``"<METHOD> <path>"`` (just the method when
    no URL could be parsed)."""
    if not url:
        return method.value
    path = urlsplit(url).path or "/"
    return f"{method.value} {path}"


def infer_body_kind(body: str | None, headers: dict[str, str]) -> BodyKind:
    """Classify a request body: trust an explicit ``Content-Type`` first, then
    fall back to the body's shape (valid JSON object/array, then form pairs)."""
    if not body:
        return BodyKind.NONE
    content_type = next((v.lower() for k, v in headers.items() if k.lower() == "content-type"), "")
    if "json" in content_type:
        return BodyKind.JSON
    if "x-www-form-urlencoded" in content_type:
        return BodyKind.FORM
    stripped = body.strip()
    if stripped[:1] in ("{", "["):
        try:
            json.loads(stripped)
        except ValueError:
            pass
        else:
            return BodyKind.JSON
    if _FORM_BODY.match(stripped):
        return BodyKind.FORM
    return BodyKind.RAW
