"""Unit tests for the pure assertion engine (SPEC §3.4, §7 "Probe + assertions"
and "Cert expiry"). No I/O: every case is a hand-built `ProbeResponse` evaluated
against a list of `Assertion`s. The engine never raises — a malformed body or a
bad path fails the relevant assertion with a clear reason."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sentinel.domain.logic.assertions import evaluate_assertions
from sentinel.domain.value_objects import Assertion, ProbeResponse

NOW = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)


def make_response(
    *,
    status_code: int = 200,
    latency_ms: int = 100,
    headers: dict[str, str] | None = None,
    body_sample: str = "",
    response_size_bytes: int = 0,
    cert_expires_at: datetime | None = None,
) -> ProbeResponse:
    return ProbeResponse(
        status_code=status_code,
        latency_ms=latency_ms,
        headers=headers or {},
        body_sample=body_sample,
        response_size_bytes=response_size_bytes,
        cert_expires_at=cert_expires_at,
    )


def evaluate_one(assertion: Assertion, response: ProbeResponse) -> bool:
    results = evaluate_assertions(response, [assertion], NOW)
    assert len(results) == 1
    assert results[0].type == assertion.type
    return results[0].passed


class TestDefaultAssertion:
    """SPEC §3.4: with no assertions, the default is status_code in 200–299."""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [(200, True), (201, True), (299, True), (300, False), (199, False), (500, False)],
    )
    def test_default_is_2xx(self, status: int, expected: bool) -> None:
        results = evaluate_assertions(make_response(status_code=status), [], NOW)
        assert len(results) == 1
        assert results[0].type == "status_code"
        assert results[0].passed is expected


class TestStatusCode:
    def test_equals(self) -> None:
        a = Assertion(type="status_code", params={"equals": 200})
        assert evaluate_one(a, make_response(status_code=200)) is True
        assert evaluate_one(a, make_response(status_code=404)) is False

    def test_in(self) -> None:
        a = Assertion(type="status_code", params={"in": [200, 201, 204]})
        assert evaluate_one(a, make_response(status_code=201)) is True
        assert evaluate_one(a, make_response(status_code=404)) is False

    def test_range(self) -> None:
        a = Assertion(type="status_code", params={"range": [200, 299]})
        assert evaluate_one(a, make_response(status_code=250)) is True
        assert evaluate_one(a, make_response(status_code=299)) is True
        assert evaluate_one(a, make_response(status_code=500)) is False

    def test_missing_params_fails_cleanly(self) -> None:
        a = Assertion(type="status_code", params={})
        assert evaluate_one(a, make_response(status_code=200)) is False


class TestLatency:
    def test_within_limit_passes(self) -> None:
        a = Assertion(type="max_latency_ms", params={"value": 800})
        assert evaluate_one(a, make_response(latency_ms=120)) is True

    def test_equal_to_limit_passes(self) -> None:
        a = Assertion(type="max_latency_ms", params={"value": 800})
        assert evaluate_one(a, make_response(latency_ms=800)) is True

    def test_over_limit_fails(self) -> None:
        a = Assertion(type="max_latency_ms", params={"value": 800})
        assert evaluate_one(a, make_response(latency_ms=900)) is False


class TestBodyContains:
    def test_present_passes(self) -> None:
        a = Assertion(type="body_contains", params={"text": "healthy"})
        assert evaluate_one(a, make_response(body_sample="status: healthy")) is True

    def test_absent_fails(self) -> None:
        a = Assertion(type="body_contains", params={"text": "healthy"})
        assert evaluate_one(a, make_response(body_sample="status: down")) is False

    def test_case_sensitive_by_default(self) -> None:
        a = Assertion(type="body_contains", params={"text": "OK"})
        assert evaluate_one(a, make_response(body_sample="all ok")) is False

    def test_case_insensitive_when_requested(self) -> None:
        a = Assertion(type="body_contains", params={"text": "OK", "case_sensitive": False})
        assert evaluate_one(a, make_response(body_sample="all ok")) is True


class TestBodyNotContains:
    def test_absent_passes(self) -> None:
        a = Assertion(type="body_not_contains", params={"text": "error"})
        assert evaluate_one(a, make_response(body_sample="all good")) is True

    def test_present_fails(self) -> None:
        a = Assertion(type="body_not_contains", params={"text": "error"})
        assert evaluate_one(a, make_response(body_sample="fatal error here")) is False


class TestJsonPathEquals:
    def test_matches(self) -> None:
        a = Assertion(type="json_path_equals", params={"path": "$.status", "value": "ok"})
        assert evaluate_one(a, make_response(body_sample='{"status": "ok"}')) is True

    def test_mismatch_fails(self) -> None:
        a = Assertion(type="json_path_equals", params={"path": "$.status", "value": "ok"})
        assert evaluate_one(a, make_response(body_sample='{"status": "degraded"}')) is False

    def test_nested_and_array(self) -> None:
        a = Assertion(
            type="json_path_equals",
            params={"path": "$.data.items[1].id", "value": 7},
        )
        body = '{"data": {"items": [{"id": 3}, {"id": 7}]}}'
        assert evaluate_one(a, make_response(body_sample=body)) is True

    def test_missing_path_fails(self) -> None:
        a = Assertion(type="json_path_equals", params={"path": "$.missing", "value": "x"})
        assert evaluate_one(a, make_response(body_sample='{"status": "ok"}')) is False

    def test_malformed_json_fails_cleanly(self) -> None:
        a = Assertion(type="json_path_equals", params={"path": "$.status", "value": "ok"})
        results = evaluate_assertions(make_response(body_sample="<html>nope"), [a], NOW)
        assert results[0].passed is False
        assert "json" in results[0].detail.lower()


class TestJsonPathExists:
    def test_present_passes(self) -> None:
        a = Assertion(type="json_path_exists", params={"path": "$.data.token"})
        assert evaluate_one(a, make_response(body_sample='{"data": {"token": "abc"}}')) is True

    def test_missing_fails(self) -> None:
        a = Assertion(type="json_path_exists", params={"path": "$.data.token"})
        assert evaluate_one(a, make_response(body_sample='{"data": {}}')) is False

    def test_present_but_null_still_exists(self) -> None:
        a = Assertion(type="json_path_exists", params={"path": "$.token"})
        assert evaluate_one(a, make_response(body_sample='{"token": null}')) is True


class TestHeaderEquals:
    def test_matches(self) -> None:
        a = Assertion(
            type="header_equals", params={"name": "Content-Type", "value": "application/json"}
        )
        resp = make_response(headers={"Content-Type": "application/json"})
        assert evaluate_one(a, resp) is True

    def test_name_match_is_case_insensitive(self) -> None:
        a = Assertion(
            type="header_equals", params={"name": "content-type", "value": "application/json"}
        )
        resp = make_response(headers={"Content-Type": "application/json"})
        assert evaluate_one(a, resp) is True

    def test_value_mismatch_fails(self) -> None:
        a = Assertion(type="header_equals", params={"name": "Content-Type", "value": "text/html"})
        resp = make_response(headers={"Content-Type": "application/json"})
        assert evaluate_one(a, resp) is False

    def test_missing_header_fails(self) -> None:
        a = Assertion(type="header_equals", params={"name": "X-Absent", "value": "y"})
        assert evaluate_one(a, make_response(headers={})) is False


class TestCertExpiryDays:
    def test_far_enough_passes(self) -> None:
        a = Assertion(type="cert_expiry_days", params={"min_days": 30})
        resp = make_response(cert_expires_at=NOW + timedelta(days=40))
        assert evaluate_one(a, resp) is True

    def test_too_near_fails(self) -> None:
        a = Assertion(type="cert_expiry_days", params={"min_days": 30})
        resp = make_response(cert_expires_at=NOW + timedelta(days=10))
        assert evaluate_one(a, resp) is False

    def test_already_expired_fails(self) -> None:
        a = Assertion(type="cert_expiry_days", params={"min_days": 1})
        resp = make_response(cert_expires_at=NOW - timedelta(days=2))
        assert evaluate_one(a, resp) is False

    def test_plain_http_is_skipped_not_failed(self) -> None:
        a = Assertion(type="cert_expiry_days", params={"min_days": 30})
        results = evaluate_assertions(make_response(cert_expires_at=None), [a], NOW)
        assert results[0].skipped is True
        # a skipped assertion must not fail the overall check
        assert results[0].passed is True


class TestMultipleAndUnknown:
    def test_returns_one_result_per_assertion_in_order(self) -> None:
        assertions = [
            Assertion(type="status_code", params={"equals": 200}),
            Assertion(type="max_latency_ms", params={"value": 50}),
        ]
        results = evaluate_assertions(
            make_response(status_code=200, latency_ms=900), assertions, NOW
        )
        assert [r.type for r in results] == ["status_code", "max_latency_ms"]
        assert [r.passed for r in results] == [True, False]
        assert not all(r.passed for r in results)

    def test_unknown_type_fails_without_raising(self) -> None:
        a = Assertion(type="nonsense", params={})
        results = evaluate_assertions(make_response(), [a], NOW)
        assert results[0].passed is False
        assert "unknown" in results[0].detail.lower()
