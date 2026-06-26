"""Pure Postman v2.1 → ``list[MonitorDraft]`` parser (SPEC §3.1, §7). A collection
is untrusted data: parsed and reshaped, never executed. Folders flatten to one
draft per request item; ``{{var}}`` resolves against the collection's ``variable``
block (unresolved vars surface as per-draft warnings, never failures); bearer/basic
request auth maps to an ``Authorization`` header (other auth types warn)."""

from __future__ import annotations

import base64
import re
from collections.abc import Iterator
from typing import Any

from sentinel.domain.logic.import_common import coerce_method, derive_name, infer_body_kind
from sentinel.domain.value_objects import BodyKind, HttpMethod, MonitorDraft

_VAR = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")
_DROPPED_BODY_MODES = {"formdata": "form-data", "file": "file", "graphql": "graphql"}


def parse_postman(collection: dict[str, Any]) -> list[MonitorDraft]:
    variables = _collect_variables(collection)
    items = collection.get("item")
    if not isinstance(items, list):
        return []
    return [_item_to_draft(item, variables) for item in _flatten(items)]


def _flatten(items: list[Any]) -> Iterator[dict[str, Any]]:
    """Depth-first walk yielding request items; folders (an item with its own
    ``item`` list) are descended into and dropped."""
    for item in items:
        if not isinstance(item, dict):
            continue
        children = item.get("item")
        if isinstance(children, list):
            yield from _flatten(children)
        elif "request" in item:
            yield item


def _collect_variables(collection: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in collection.get("variable") or []:
        if isinstance(entry, dict) and "key" in entry:
            out[str(entry["key"])] = str(entry.get("value", ""))
    return out


def _item_to_draft(item: dict[str, Any], variables: dict[str, str]) -> MonitorDraft:
    warnings: list[str] = []
    unresolved: list[str] = []

    request = item.get("request")
    if isinstance(request, str):
        request = {"url": request}
    elif not isinstance(request, dict):
        request = {}

    method_raw = request.get("method")
    method = (
        coerce_method(method_raw, warnings)
        if isinstance(method_raw, str) and method_raw
        else HttpMethod.GET
    )

    url = _resolve(_extract_url(request), variables, unresolved)
    headers = _extract_headers(request, variables, unresolved)

    auth = request.get("auth")
    if isinstance(auth, dict):
        _apply_auth(auth, headers, variables, unresolved, warnings)

    body, body_kind = _extract_body(request, headers, variables, unresolved, warnings)

    for var in unresolved:
        warnings.append("unresolved variable: {{" + var + "}}")

    item_name = item.get("name")
    if isinstance(item_name, str) and item_name.strip():
        name = item_name
    else:
        name = derive_name(method, url)

    return MonitorDraft(
        name=name,
        url=url,
        method=method,
        headers=headers,
        body=body,
        body_kind=body_kind,
        warnings=warnings,
    )


def _resolve(text: str, variables: dict[str, str], unresolved: list[str]) -> str:
    """Substitute ``{{var}}`` placeholders; an undefined var is left in place and
    recorded once (insertion order) for a later warning."""

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in variables:
            return variables[key]
        if key not in unresolved:
            unresolved.append(key)
        return match.group(0)

    return _VAR.sub(repl, text)


def _extract_url(request: dict[str, Any]) -> str:
    url = request.get("url")
    if isinstance(url, str):
        return url
    if isinstance(url, dict):
        raw = url.get("raw")
        return raw if isinstance(raw, str) else _build_url(url)
    return ""


def _build_url(url: dict[str, Any]) -> str:
    host = url.get("host")
    path = url.get("path")
    host_s = ".".join(host) if isinstance(host, list) else host if isinstance(host, str) else ""
    path_s = (
        "/".join(str(p) for p in path)
        if isinstance(path, list)
        else path
        if isinstance(path, str)
        else ""
    )
    if host_s and path_s:
        return f"{host_s}/{path_s}"
    return host_s or path_s


def _extract_headers(
    request: dict[str, Any], variables: dict[str, str], unresolved: list[str]
) -> dict[str, str]:
    headers: dict[str, str] = {}
    raw = request.get("header")
    if not isinstance(raw, list):
        return headers
    for entry in raw:
        if not isinstance(entry, dict) or entry.get("disabled"):
            continue
        key = entry.get("key")
        if not isinstance(key, str):
            continue
        value = _resolve(str(entry.get("value", "")), variables, unresolved)
        headers[_resolve(key, variables, unresolved)] = value
    return headers


def _apply_auth(
    auth: dict[str, Any],
    headers: dict[str, str],
    variables: dict[str, str],
    unresolved: list[str],
    warnings: list[str],
) -> None:
    auth_type = auth.get("type")
    if auth_type == "bearer":
        token = _resolve(_auth_param(auth.get("bearer"), "token"), variables, unresolved)
        headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "basic":
        user = _resolve(_auth_param(auth.get("basic"), "username"), variables, unresolved)
        password = _resolve(_auth_param(auth.get("basic"), "password"), variables, unresolved)
        encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
    elif isinstance(auth_type, str) and auth_type != "noauth":
        warnings.append(f"auth type '{auth_type}' not imported")


def _auth_param(entries: Any, key: str) -> str:
    if isinstance(entries, dict):
        return str(entries.get(key, ""))
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and entry.get("key") == key:
                return str(entry.get("value", ""))
    return ""


def _extract_body(
    request: dict[str, Any],
    headers: dict[str, str],
    variables: dict[str, str],
    unresolved: list[str],
    warnings: list[str],
) -> tuple[str | None, BodyKind]:
    body_obj = request.get("body")
    if not isinstance(body_obj, dict):
        return None, BodyKind.NONE
    mode = body_obj.get("mode")
    if mode == "raw":
        raw = body_obj.get("raw")
        if not isinstance(raw, str) or not raw:
            return None, BodyKind.NONE
        body = _resolve(raw, variables, unresolved)
        if _raw_language(body_obj) == "json":
            return body, BodyKind.JSON
        return body, infer_body_kind(body, headers)
    if mode == "urlencoded":
        body = _join_pairs(body_obj.get("urlencoded"), variables, unresolved)
        return (body, BodyKind.FORM) if body else (None, BodyKind.NONE)
    if isinstance(mode, str) and mode in _DROPPED_BODY_MODES:
        warnings.append(f"{_DROPPED_BODY_MODES[mode]} body not imported")
    return None, BodyKind.NONE


def _raw_language(body_obj: dict[str, Any]) -> str | None:
    options = body_obj.get("options")
    raw_opts = options.get("raw") if isinstance(options, dict) else None
    language = raw_opts.get("language") if isinstance(raw_opts, dict) else None
    return language.lower() if isinstance(language, str) else None


def _join_pairs(pairs: Any, variables: dict[str, str], unresolved: list[str]) -> str:
    if not isinstance(pairs, list):
        return ""
    parts: list[str] = []
    for entry in pairs:
        if not isinstance(entry, dict) or entry.get("disabled"):
            continue
        key = entry.get("key")
        if not isinstance(key, str):
            continue
        value = _resolve(str(entry.get("value", "")), variables, unresolved)
        parts.append(f"{_resolve(key, variables, unresolved)}={value}")
    return "&".join(parts)
