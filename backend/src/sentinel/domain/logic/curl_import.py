"""Pure `curl` → `MonitorDraft` parser (SPEC §3.1, §5). No I/O, no execution —
the command string is untrusted data. Supports `-X`/`--request`, `-H`/`--header`,
`-d`/`--data*`, `--url`/bare URL, `-u`/`--user` (→ Basic auth header),
`--compressed`, `-L`/`--location`. Unrecognized flags are dropped with a warning."""

from __future__ import annotations

import base64
import shlex

from sentinel.domain.logic.import_common import coerce_method, derive_name, infer_body_kind
from sentinel.domain.value_objects import HttpMethod, MonitorDraft

_METHOD_FLAGS = {"-X", "--request"}
_HEADER_FLAGS = {"-H", "--header"}
_DATA_FLAGS = {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode"}
_URL_FLAGS = {"--url"}
_USER_FLAGS = {"-u", "--user"}
_FOLLOW_FLAGS = {"-L", "--location"}
_KNOWN_BOOL_FLAGS = {"--compressed"}  # recognized; no bearing on a monitor draft


def parse_curl(command: str) -> MonitorDraft:
    headers: dict[str, str] = {}
    data_parts: list[str] = []
    warnings: list[str] = []
    method: str | None = None
    url: str | None = None
    user: str | None = None
    follow_redirects = False

    tokens = _tokenize(command)
    index = 1 if tokens and tokens[0] == "curl" else 0
    while index < len(tokens):
        arg = tokens[index]
        if arg in _METHOD_FLAGS:
            value, index = _take_value(tokens, index, arg, warnings)
            method = value.upper() if value else method
        elif arg.startswith("-X") and len(arg) > 2:
            method, index = arg[2:].upper(), index + 1
        elif arg in _HEADER_FLAGS:
            value, index = _take_value(tokens, index, arg, warnings)
            _add_header(headers, value, warnings)
        elif arg.startswith("-H") and len(arg) > 2:
            _add_header(headers, arg[2:], warnings)
            index += 1
        elif arg in _DATA_FLAGS:
            value, index = _take_value(tokens, index, arg, warnings)
            if value is not None:
                data_parts.append(value)
        elif arg in _URL_FLAGS:
            value, index = _take_value(tokens, index, arg, warnings)
            url = _set_url(url, value, warnings)
        elif arg in _USER_FLAGS:
            user, index = _take_value(tokens, index, arg, warnings)
        elif arg.startswith("-u") and len(arg) > 2:
            user, index = arg[2:], index + 1
        elif arg in _FOLLOW_FLAGS:
            follow_redirects, index = True, index + 1
        elif arg in _KNOWN_BOOL_FLAGS:
            index += 1
        elif arg.startswith("-") and arg != "-":
            warnings.append(f"ignored unsupported flag: {arg}")
            index += 1
        else:
            url = _set_url(url, arg, warnings)
            index += 1

    if user is not None:
        headers["Authorization"] = "Basic " + base64.b64encode(user.encode()).decode()

    resolved_method = _resolve_method(method, has_data=bool(data_parts), warnings=warnings)
    body = "&".join(data_parts) if data_parts else None
    if url is None:
        warnings.append("no URL found in command")
        url = ""

    return MonitorDraft(
        name=derive_name(resolved_method, url),
        url=url,
        method=resolved_method,
        headers=headers,
        body=body,
        body_kind=infer_body_kind(body, headers),
        follow_redirects=follow_redirects,
        warnings=warnings,
    )


def _tokenize(command: str) -> list[str]:
    normalized = command.replace("\\\r\n", " ").replace("\\\n", " ")
    try:
        return shlex.split(normalized)
    except ValueError:
        return normalized.split()


def _take_value(
    tokens: list[str], index: int, flag: str, warnings: list[str]
) -> tuple[str | None, int]:
    if index + 1 < len(tokens):
        return tokens[index + 1], index + 2
    warnings.append(f"flag {flag} expected a value")
    return None, index + 1


def _add_header(headers: dict[str, str], raw: str | None, warnings: list[str]) -> None:
    if raw is None:
        return
    if ":" not in raw:
        warnings.append(f"could not parse header: {raw}")
        return
    name, _, value = raw.partition(":")
    headers[name.strip()] = value.strip()


def _set_url(current: str | None, value: str | None, warnings: list[str]) -> str | None:
    if value is None:
        return current
    if current is not None:
        warnings.append(f"ignored unexpected argument: {value}")
        return current
    return value


def _resolve_method(method: str | None, *, has_data: bool, warnings: list[str]) -> HttpMethod:
    if method is None:
        return HttpMethod.POST if has_data else HttpMethod.GET
    return coerce_method(method, warnings)
