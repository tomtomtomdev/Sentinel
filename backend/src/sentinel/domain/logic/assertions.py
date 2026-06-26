"""Pure assertion engine (SPEC §3.4). Evaluates a `ProbeResponse` against a
monitor's assertions with zero I/O — no network, and the current time is passed
in (not read from a clock) so cert-expiry math is deterministic in tests.

A check's success is ``all(r.passed for r in results)``. A malformed body, a
missing JSON path, bad params, or an unknown assertion type fails the relevant
assertion with a clear ``detail`` — `evaluate_assertions` never raises."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sentinel.domain.logic.json_path import MISSING, resolve_json_path
from sentinel.domain.value_objects import Assertion, AssertionResult, ProbeResponse

# SPEC §3.4: with no assertions configured, the default check is 2xx.
_DEFAULT_ASSERTION = Assertion(type="status_code", params={"range": [200, 299]})

Evaluator = Callable[[ProbeResponse, dict[str, Any], datetime], AssertionResult]


def evaluate_assertions(
    response: ProbeResponse, assertions: list[Assertion], now: datetime
) -> list[AssertionResult]:
    items = assertions or [_DEFAULT_ASSERTION]
    return [_evaluate_one(response, a, now) for a in items]


def _evaluate_one(response: ProbeResponse, assertion: Assertion, now: datetime) -> AssertionResult:
    evaluator = _EVALUATORS.get(assertion.type)
    if evaluator is None:
        return _r(assertion.type, False, f"unknown assertion type: {assertion.type!r}")
    try:
        return evaluator(response, assertion.params, now)
    except Exception as exc:
        # The engine is pure and must never raise; bad params surface as a failure.
        return _r(assertion.type, False, f"assertion error: {exc}")


def _r(type_: str, passed: bool, detail: str, *, skipped: bool = False) -> AssertionResult:
    return AssertionResult(type=type_, passed=passed, detail=detail, skipped=skipped)


def _status_code(response: ProbeResponse, params: dict[str, Any], now: datetime) -> AssertionResult:
    code = response.status_code
    if "equals" in params:
        target = params["equals"]
        return _r("status_code", code == target, f"status {code} == {target}")
    if "in" in params:
        allowed = params["in"]
        return _r("status_code", code in allowed, f"status {code} in {allowed}")
    if "range" in params:
        lo, hi = params["range"]
        return _r("status_code", lo <= code <= hi, f"status {code} in [{lo}, {hi}]")
    return _r("status_code", False, "status_code assertion needs equals/in/range")


def _max_latency_ms(
    response: ProbeResponse, params: dict[str, Any], now: datetime
) -> AssertionResult:
    limit = params["value"]
    return _r(
        "max_latency_ms",
        response.latency_ms <= limit,
        f"latency {response.latency_ms}ms <= {limit}ms",
    )


def _body_contains(
    response: ProbeResponse, params: dict[str, Any], now: datetime
) -> AssertionResult:
    text = params["text"]
    haystack = response.body_sample
    if not params.get("case_sensitive", True):
        text, haystack = text.lower(), haystack.lower()
    return _r("body_contains", text in haystack, f"body contains {params['text']!r}")


def _body_not_contains(
    response: ProbeResponse, params: dict[str, Any], now: datetime
) -> AssertionResult:
    text = params["text"]
    haystack = response.body_sample
    if not params.get("case_sensitive", True):
        text, haystack = text.lower(), haystack.lower()
    return _r("body_not_contains", text not in haystack, f"body lacks {params['text']!r}")


def _json_path_equals(
    response: ProbeResponse, params: dict[str, Any], now: datetime
) -> AssertionResult:
    path, expected = params["path"], params["value"]
    try:
        data = json.loads(response.body_sample)
    except (json.JSONDecodeError, ValueError) as exc:
        return _r("json_path_equals", False, f"response body is not valid JSON: {exc}")
    actual = resolve_json_path(data, path)
    if actual is MISSING:
        return _r("json_path_equals", False, f"path {path} did not resolve")
    return _r("json_path_equals", actual == expected, f"{path} = {actual!r}, expected {expected!r}")


def _json_path_exists(
    response: ProbeResponse, params: dict[str, Any], now: datetime
) -> AssertionResult:
    path = params["path"]
    try:
        data = json.loads(response.body_sample)
    except (json.JSONDecodeError, ValueError) as exc:
        return _r("json_path_exists", False, f"response body is not valid JSON: {exc}")
    exists = resolve_json_path(data, path) is not MISSING
    return _r("json_path_exists", exists, f"path {path} {'resolved' if exists else 'missing'}")


def _header_equals(
    response: ProbeResponse, params: dict[str, Any], now: datetime
) -> AssertionResult:
    name, expected = params["name"], params["value"]
    lowered = {k.lower(): v for k, v in response.headers.items()}
    actual = lowered.get(name.lower())
    return _r(
        "header_equals", actual == expected, f"header {name} = {actual!r}, expected {expected!r}"
    )


def _cert_expiry_days(
    response: ProbeResponse, params: dict[str, Any], now: datetime
) -> AssertionResult:
    min_days = params["min_days"]
    if response.cert_expires_at is None:
        return _r(
            "cert_expiry_days",
            True,
            "no TLS certificate (plain HTTP) — not applicable",
            skipped=True,
        )
    remaining = response.cert_expires_at - now
    return _r(
        "cert_expiry_days",
        remaining >= timedelta(days=min_days),
        f"cert valid for {remaining.days}d, need >= {min_days}d",
    )


_EVALUATORS: dict[str, Evaluator] = {
    "status_code": _status_code,
    "max_latency_ms": _max_latency_ms,
    "body_contains": _body_contains,
    "body_not_contains": _body_not_contains,
    "json_path_equals": _json_path_equals,
    "json_path_exists": _json_path_exists,
    "header_equals": _header_equals,
    "cert_expiry_days": _cert_expiry_days,
}
