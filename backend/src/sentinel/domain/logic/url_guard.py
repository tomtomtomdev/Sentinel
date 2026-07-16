"""Pure SSRF-guard classification (SPEC §6). Two I/O-free predicates behind the
resolve-then-validate guard: `invalid_url_reason` rejects URLs that must never be
fetched regardless of DNS (non-http(s) scheme, no host), and `blocked_ip_reason`
classifies one resolved IP against the deny-list — loopback, link-local (incl.
the cloud metadata endpoint `169.254.169.254`), private, unspecified, multicast,
reserved. Resolution itself is I/O and lives in `infrastructure.url_guard`.

Reasons are short, human-readable, and deliberately never embed the URL, host,
or IP: they flow into `NotificationLog.detail` and refresh errors, and a webhook
URL is itself a secret (SPEC §6)."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def invalid_url_reason(url: str) -> str | None:
    """Why `url` must not be fetched at all, or `None` if it looks fetchable.
    Purely syntactic — the resolved-IP check is the guard's second phase."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return "blocked: URL could not be parsed"
    if parts.scheme not in _ALLOWED_SCHEMES:
        return "blocked: URL scheme must be http or https"
    if not host:
        return "blocked: URL has no host"
    return None


def blocked_ip_reason(ip: str) -> str | None:
    """Why the resolved address `ip` is off-limits, or `None` for a public one.
    An unparseable value is blocked, not crashed — fail closed. IPv4-mapped IPv6
    (`::ffff:10.0.0.1`) is unwrapped so the v4 ranges can't be smuggled past."""
    try:
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(ip)
    except ValueError:
        return "blocked: unrecognized IP address"
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    # Specific categories first: `is_private` is a superset of several of them.
    if address.is_loopback:
        return "blocked: loopback address"
    if address.is_link_local:
        return "blocked: link-local address"
    if address.is_unspecified:
        return "blocked: unspecified address"
    if address.is_multicast:
        return "blocked: multicast address"
    if address.is_private:
        return "blocked: private address"
    if address.is_reserved:
        return "blocked: reserved address"
    return None
