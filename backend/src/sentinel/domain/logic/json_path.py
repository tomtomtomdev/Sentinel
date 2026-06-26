"""Minimal JSONPath resolver used by the assertion engine (and, later, auth-source
token extraction). Supports the common subset the SPEC examples use: a leading
``$``, dotted keys (``$.a.b``), bracketed string keys (``$['a']`` / ``$["a"]``),
and array indices (``$.items[0]``, including negative). Returns the ``MISSING``
sentinel when a segment doesn't resolve; raises ``ValueError`` for a syntactically
invalid path expression. Pure — no I/O.

Full JSONPath (filters, wildcards, recursive descent) is intentionally out of
scope for v1; extend here if a monitor ever needs it."""

from __future__ import annotations

import re
from typing import Any

MISSING = object()

_SEGMENT = re.compile(
    r"""
      \.(?P<dot>[^.\[\]]+)         # .key
    | \[(?P<index>-?\d+)\]         # [0] or [-1]
    | \['(?P<sq>[^']*)'\]          # ['key']
    | \["(?P<dq>[^"]*)"\]          # ["key"]
    """,
    re.VERBOSE,
)


def _tokens(path: str) -> list[str | int]:
    expr = path[1:] if path.startswith("$") else path
    tokens: list[str | int] = []
    pos = 0
    while pos < len(expr):
        match = _SEGMENT.match(expr, pos)
        if match is None:
            raise ValueError(f"invalid json path: {path!r}")
        if match.group("index") is not None:
            tokens.append(int(match.group("index")))
        elif match.group("dot") is not None:
            tokens.append(match.group("dot"))
        elif match.group("sq") is not None:
            tokens.append(match.group("sq"))
        else:
            tokens.append(match.group("dq"))
        pos = match.end()
    return tokens


def resolve_json_path(data: Any, path: str) -> Any:
    """Return the value at ``path`` within ``data``, or ``MISSING`` if any segment
    does not resolve. Raises ``ValueError`` for a malformed path expression."""
    current: Any = data
    for token in _tokens(path):
        if isinstance(token, int):
            if isinstance(current, list) and -len(current) <= token < len(current):
                current = current[token]
            else:
                return MISSING
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            return MISSING
    return current
