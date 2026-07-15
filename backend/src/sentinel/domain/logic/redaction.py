"""Header redaction (SPEC §6, sentinel-security rule 1). One pure helper, applied
at the serialization boundary so secret values never reach a response or a log.
The header key is preserved (the user still sees the header exists); only the
value is masked."""

from __future__ import annotations

from typing import Any

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


# Substrings that mark an alert-channel config key as carrying a secret value
# (case-insensitive), e.g. `bot_token`, `client_secret`, `smtp_password`, `api_key`.
_SECRET_CONFIG_SUBSTRINGS = ("token", "secret", "key", "password", "passwd")


def is_secret_config_key(key: str) -> bool:
    """Whether an `AlertChannel.config` key carries a secret value (SPEC §3.7, §6).
    The single source of truth for "which config values are secret", shared by API
    redaction and at-rest encryption so the two can never drift (cf. `is_secret_header`)."""
    lowered = key.lower()
    return any(token in lowered for token in _SECRET_CONFIG_SUBSTRINGS)


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a channel `config` with secret values masked (SPEC §6). The
    key is kept so the user sees the setting exists; non-secret values pass through
    unchanged. Never mutates the input."""
    return {key: (MASK if is_secret_config_key(key) else value) for key, value in config.items()}
