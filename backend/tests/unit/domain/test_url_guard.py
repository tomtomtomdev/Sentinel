"""Pure SSRF-guard classification (SPEC §6, sentinel-security §3). Two I/O-free
functions: `invalid_url_reason` rejects non-http(s)/host-less URLs before any DNS,
and `blocked_ip_reason` classifies a single resolved IP against the deny-list
(loopback, link-local incl. the cloud metadata IP, private, unspecified,
multicast). Reasons are short and never embed the URL, host, or IP — a webhook
URL is itself a secret and the reason may land in a `NotificationLog.detail`."""

from __future__ import annotations

import pytest

from sentinel.domain.logic.url_guard import blocked_ip_reason, invalid_url_reason


class TestInvalidUrlReason:
    @pytest.mark.parametrize(
        "url",
        [
            "https://api.example.com/health",
            "http://api.example.com",
            "https://api.example.com:8443/v1?x=1",
        ],
    )
    def test_http_and_https_urls_with_a_host_pass(self, url: str) -> None:
        assert invalid_url_reason(url) is None

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://files.example.com/x",
            "file:///etc/passwd",
            "gopher://example.com",
            "javascript:alert(1)",
            "example.com/no-scheme",
        ],
    )
    def test_non_http_schemes_are_rejected(self, url: str) -> None:
        reason = invalid_url_reason(url)
        assert reason is not None
        assert "http" in reason  # says what *is* allowed, not the URL itself

    @pytest.mark.parametrize("url", ["https://", "http:///path", ""])
    def test_url_without_a_host_is_rejected(self, url: str) -> None:
        assert invalid_url_reason(url) is not None

    def test_reason_never_echoes_the_url(self) -> None:
        reason = invalid_url_reason("ftp://secret-host.internal/creds")
        assert reason is not None
        assert "secret-host" not in reason


class TestBlockedIpReason:
    @pytest.mark.parametrize(
        ("ip", "expected_word"),
        [
            ("127.0.0.1", "loopback"),
            ("127.8.8.8", "loopback"),
            ("::1", "loopback"),
            ("169.254.169.254", "link-local"),  # cloud metadata endpoint
            ("169.254.1.1", "link-local"),
            ("fe80::1", "link-local"),
            ("10.0.0.1", "private"),
            ("172.16.0.1", "private"),
            ("172.31.255.255", "private"),
            ("192.168.1.1", "private"),
            ("fc00::1", "private"),
            ("fd12:3456::1", "private"),
            ("0.0.0.0", "unspecified"),  # noqa: S104 -- deny-list fixture, not a bind
            ("::", "unspecified"),
            ("224.0.0.1", "multicast"),
            ("ff02::1", "multicast"),
        ],
    )
    def test_blocked_ranges_are_rejected_with_a_named_reason(
        self, ip: str, expected_word: str
    ) -> None:
        reason = blocked_ip_reason(ip)
        assert reason is not None
        assert expected_word in reason
        assert ip not in reason  # the IP itself never leaks into the reason

    def test_ipv4_mapped_ipv6_is_unwrapped_before_classification(self) -> None:
        assert blocked_ip_reason("::ffff:10.0.0.1") is not None
        assert blocked_ip_reason("::ffff:127.0.0.1") is not None

    @pytest.mark.parametrize(
        "ip",
        [
            "8.8.8.8",
            "1.1.1.1",
            "93.184.216.34",
            "172.32.0.1",  # just past 172.16/12
            "2606:4700:4700::1111",
        ],
    )
    def test_public_addresses_pass(self, ip: str) -> None:
        assert blocked_ip_reason(ip) is None

    def test_unparseable_ip_is_blocked_not_crashed(self) -> None:
        assert blocked_ip_reason("not-an-ip") is not None
