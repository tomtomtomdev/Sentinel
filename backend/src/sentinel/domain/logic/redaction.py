"""Header redaction (SPEC §6, sentinel-security rule 1). One pure helper, applied
at the serialization boundary so secret values never reach a response or a log.
The header key is preserved (the user still sees the header exists); only the
value is masked."""

from __future__ import annotations

MASK = "••••"

# Header names whose value is always a secret (matched case-insensitively).
_SECRET_HEADER_NAMES = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
    }
)

# Substrings that mark a header as secret-bearing by convention.
_SECRET_SUBSTRINGS = ("token", "secret", "key")

# Headers carrying a "<scheme> <credential>" value, where the scheme is kept
# (e.g. "Bearer ••••") so the user can see the auth type without the secret.
_SCHEME_HEADER_NAMES = frozenset({"authorization", "proxy-authorization"})


def is_secret_header(name: str) -> bool:
    """Whether a header name carries a secret value (case-insensitive). The single
    source of truth for "what is secret", shared by API redaction and at-rest
    encryption so the two never drift."""
    lowered = name.lower()
    if lowered in _SECRET_HEADER_NAMES:
        return True
    return any(token in lowered for token in _SECRET_SUBSTRINGS)


def redact(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of `headers` with secret-bearing values masked.

    Authorization-style headers keep their scheme (``Bearer ••••``); all other
    secret headers are fully masked (``••••``). Non-secret headers pass through.
    Never mutates the input.
    """
    redacted: dict[str, str] = {}
    for name, value in headers.items():
        if not is_secret_header(name):
            redacted[name] = value
        elif name.lower() in _SCHEME_HEADER_NAMES and " " in value:
            scheme = value.split(" ", 1)[0]
            redacted[name] = f"{scheme} {MASK}"
        else:
            redacted[name] = MASK
    return redacted
