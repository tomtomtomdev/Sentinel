from uuid import UUID

import pytest

from sentinel.domain.entities import Monitor
from sentinel.domain.errors import ValidationError
from sentinel.domain.value_objects import Assertion, Auth, AuthType, BodyKind, HttpMethod


def make_monitor(**overrides: object) -> Monitor:
    params: dict[str, object] = {"name": "Prod health", "url": "https://api.example.com/health"}
    params.update(overrides)
    return Monitor(**params)  # type: ignore[arg-type]


class TestMonitorDefaults:
    """SPEC §3.3 / §4 — defaults applied when fields are omitted."""

    def test_minimal_monitor_applies_spec_defaults(self) -> None:
        m = make_monitor()
        assert m.method is HttpMethod.GET
        assert m.interval_seconds == 300
        assert m.timeout_seconds == 10
        assert m.follow_redirects is True
        assert m.failure_threshold == 1
        assert m.recovery_threshold == 1
        assert m.enabled is True
        assert m.body_kind is BodyKind.NONE
        assert m.body is None
        assert m.headers == {}
        assert m.query_params == {}
        assert m.assertions == []
        assert m.tags == []
        assert m.auth is None
        assert m.auth_source_id is None
        assert m.created_at is None
        assert m.updated_at is None
        assert isinstance(m.id, UUID)

    def test_distinct_monitors_get_distinct_ids(self) -> None:
        assert make_monitor().id != make_monitor().id

    def test_accepts_auth_and_assertions(self) -> None:
        m = make_monitor(
            auth=Auth(type=AuthType.BEARER, secret_ref="ref-1"),
            assertions=[Assertion(type="status_code", params={"equals": 200})],
        )
        assert m.auth == Auth(type=AuthType.BEARER, secret_ref="ref-1")
        assert m.assertions[0].type == "status_code"


class TestMonitorInvariants:
    """SPEC §4 — field constraints rejected at construction."""

    def test_interval_below_minimum_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_monitor(interval_seconds=29)

    def test_interval_minimum_allowed(self) -> None:
        assert make_monitor(interval_seconds=30).interval_seconds == 30

    def test_timeout_below_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_monitor(timeout_seconds=0)

    def test_timeout_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_monitor(timeout_seconds=61)

    def test_timeout_bounds_allowed(self) -> None:
        assert make_monitor(timeout_seconds=1).timeout_seconds == 1
        assert make_monitor(timeout_seconds=60).timeout_seconds == 60

    def test_failure_threshold_below_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_monitor(failure_threshold=0)

    def test_recovery_threshold_below_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_monitor(recovery_threshold=0)

    def test_blank_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_monitor(name="   ")

    def test_blank_url_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_monitor(url="")
