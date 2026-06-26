"""Unit test for the TLS `notAfter` parser (SPEC §7 "Cert expiry"). The cert-
expiry assertion *logic* is covered by the pure engine; this covers parsing the
OpenSSL date string the probe reads off the peer certificate. No network."""

from __future__ import annotations

from datetime import UTC, datetime

from sentinel.infrastructure.probe import parse_cert_not_after


def test_parses_openssl_not_after_to_utc() -> None:
    assert parse_cert_not_after("Jun 26 12:00:00 2027 GMT") == datetime(
        2027, 6, 26, 12, 0, 0, tzinfo=UTC
    )


def test_parses_single_digit_day() -> None:
    assert parse_cert_not_after("Sep  1 00:00:00 2026 GMT") == datetime(
        2026, 9, 1, 0, 0, 0, tzinfo=UTC
    )
