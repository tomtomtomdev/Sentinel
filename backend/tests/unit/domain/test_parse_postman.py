"""Pure Postman v2.1 parser (SPEC §3.1, §7 import-postman). A collection is
untrusted data — flattened into reviewable drafts, never executed. Folders flatten
to one draft per request item; `{{var}}` resolves against the collection's
`variable` block; unresolved vars surface as per-draft warnings, never failures."""

from __future__ import annotations

import base64
from typing import Any

from sentinel.domain.logic.postman_import import parse_postman
from sentinel.domain.value_objects import BodyKind, HttpMethod


def _request_item(name: str, **request: Any) -> dict[str, Any]:
    return {"name": name, "request": request}


_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


def _collection(
    items: list[dict[str, Any]], variables: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    collection: dict[str, Any] = {
        "info": {"name": "C", "schema": _SCHEMA},
        "item": items,
    }
    if variables is not None:
        collection["variable"] = variables
    return collection


class TestFlattening:
    def test_empty_collection_yields_no_drafts(self) -> None:
        assert parse_postman({"info": {"name": "C"}}) == []
        assert parse_postman(_collection([])) == []

    def test_one_draft_per_top_level_request(self) -> None:
        col = _collection(
            [
                _request_item("A", method="GET", url="https://x/a"),
                _request_item("B", method="GET", url="https://x/b"),
            ]
        )
        drafts = parse_postman(col)
        assert [d.name for d in drafts] == ["A", "B"]

    def test_folders_are_flattened(self) -> None:
        col = _collection(
            [
                {
                    "name": "Folder",
                    "item": [_request_item("Inner", method="GET", url="https://x/i")],
                },
                _request_item("Top", method="GET", url="https://x/t"),
            ]
        )
        drafts = parse_postman(col)
        assert [d.name for d in drafts] == ["Inner", "Top"]

    def test_deeply_nested_folders_are_flattened(self) -> None:
        col = _collection(
            [
                {
                    "name": "Outer",
                    "item": [
                        {
                            "name": "Inner",
                            "item": [_request_item("Deep", method="GET", url="https://x/d")],
                        }
                    ],
                }
            ]
        )
        drafts = parse_postman(col)
        assert [d.name for d in drafts] == ["Deep"]


class TestVariableResolution:
    def test_resolves_var_in_url(self) -> None:
        col = _collection(
            [_request_item("Health", method="GET", url="{{baseUrl}}/health")],
            variables=[{"key": "baseUrl", "value": "https://api.example.com"}],
        )
        draft = parse_postman(col)[0]
        assert draft.url == "https://api.example.com/health"
        assert draft.warnings == []

    def test_resolves_var_in_header_and_body(self) -> None:
        col = _collection(
            [
                _request_item(
                    "Create",
                    method="POST",
                    header=[{"key": "X-Tenant", "value": "{{tenant}}"}],
                    body={"mode": "raw", "raw": '{"tenant":"{{tenant}}"}'},
                    url="{{baseUrl}}/x",
                )
            ],
            variables=[
                {"key": "baseUrl", "value": "https://x"},
                {"key": "tenant", "value": "acme"},
            ],
        )
        draft = parse_postman(col)[0]
        assert draft.headers["X-Tenant"] == "acme"
        assert draft.body == '{"tenant":"acme"}'
        assert draft.warnings == []

    def test_undefined_var_warns_and_is_left_in_place(self) -> None:
        col = _collection(
            [_request_item("Item", method="GET", url="{{baseUrl}}/items/{{itemId}}")],
            variables=[{"key": "baseUrl", "value": "https://x"}],
        )
        draft = parse_postman(col)[0]
        assert draft.url == "https://x/items/{{itemId}}"
        assert any("itemId" in w for w in draft.warnings)

    def test_undefined_var_is_warned_once_per_name(self) -> None:
        col = _collection(
            [_request_item("Item", method="GET", url="{{missing}}/{{missing}}")],
        )
        draft = parse_postman(col)[0]
        assert sum("missing" in w for w in draft.warnings) == 1

    def test_no_variable_block_is_not_a_failure(self) -> None:
        col = _collection([_request_item("Item", method="GET", url="{{baseUrl}}/x")])
        draft = parse_postman(col)[0]
        assert draft.url == "{{baseUrl}}/x"
        assert any("baseUrl" in w for w in draft.warnings)


class TestRequestFields:
    def test_method_extracted(self) -> None:
        col = _collection([_request_item("D", method="DELETE", url="https://x/y")])
        assert parse_postman(col)[0].method is HttpMethod.DELETE

    def test_missing_method_defaults_to_get(self) -> None:
        col = _collection([{"name": "N", "request": {"url": "https://x/y"}}])
        assert parse_postman(col)[0].method is HttpMethod.GET

    def test_unsupported_method_warns_and_defaults_to_get(self) -> None:
        col = _collection([_request_item("P", method="PURGE", url="https://x/y")])
        draft = parse_postman(col)[0]
        assert draft.method is HttpMethod.GET
        assert any("PURGE" in w for w in draft.warnings)

    def test_headers_extracted_from_array(self) -> None:
        col = _collection(
            [
                _request_item(
                    "H",
                    method="GET",
                    url="https://x/y",
                    header=[
                        {"key": "Accept", "value": "application/json"},
                        {"key": "X-Api-Key", "value": "k"},
                    ],
                )
            ]
        )
        assert parse_postman(col)[0].headers == {"Accept": "application/json", "X-Api-Key": "k"}

    def test_disabled_header_is_skipped(self) -> None:
        col = _collection(
            [
                _request_item(
                    "H",
                    method="GET",
                    url="https://x/y",
                    header=[
                        {"key": "Accept", "value": "application/json"},
                        {"key": "X-Off", "value": "v", "disabled": True},
                    ],
                )
            ]
        )
        assert parse_postman(col)[0].headers == {"Accept": "application/json"}

    def test_url_as_object_uses_raw(self) -> None:
        col = _collection(
            [
                _request_item(
                    "U",
                    method="GET",
                    url={"raw": "https://x/y?a=1", "host": ["x"], "path": ["y"]},
                )
            ]
        )
        assert parse_postman(col)[0].url == "https://x/y?a=1"

    def test_secret_header_is_not_redacted(self) -> None:
        col = _collection(
            [
                _request_item(
                    "H",
                    method="GET",
                    url="https://x/y",
                    header=[{"key": "Authorization", "value": "Bearer supersecret"}],
                )
            ]
        )
        assert parse_postman(col)[0].headers["Authorization"] == "Bearer supersecret"


class TestBody:
    def test_raw_json_language_sets_json_kind(self) -> None:
        col = _collection(
            [
                _request_item(
                    "J",
                    method="POST",
                    url="https://x/y",
                    body={
                        "mode": "raw",
                        "raw": '{"a":1}',
                        "options": {"raw": {"language": "json"}},
                    },
                )
            ]
        )
        draft = parse_postman(col)[0]
        assert draft.body == '{"a":1}'
        assert draft.body_kind is BodyKind.JSON

    def test_raw_json_inferred_by_shape(self) -> None:
        col = _collection(
            [
                _request_item(
                    "J", method="POST", url="https://x/y", body={"mode": "raw", "raw": '{"a":1}'}
                )
            ]
        )
        assert parse_postman(col)[0].body_kind is BodyKind.JSON

    def test_urlencoded_body_joined_as_form(self) -> None:
        col = _collection(
            [
                _request_item(
                    "F",
                    method="POST",
                    url="https://x/y",
                    body={
                        "mode": "urlencoded",
                        "urlencoded": [
                            {"key": "a", "value": "1"},
                            {"key": "b", "value": "2"},
                            {"key": "c", "value": "3", "disabled": True},
                        ],
                    },
                )
            ]
        )
        draft = parse_postman(col)[0]
        assert draft.body == "a=1&b=2"
        assert draft.body_kind is BodyKind.FORM

    def test_formdata_body_warns_and_is_dropped(self) -> None:
        col = _collection(
            [
                _request_item(
                    "M",
                    method="POST",
                    url="https://x/y",
                    body={"mode": "formdata", "formdata": [{"key": "f", "value": "v"}]},
                )
            ]
        )
        draft = parse_postman(col)[0]
        assert draft.body is None
        assert draft.body_kind is BodyKind.NONE
        assert any("form-data" in w for w in draft.warnings)

    def test_empty_raw_body_is_none(self) -> None:
        col = _collection(
            [_request_item("E", method="POST", url="https://x/y", body={"mode": "raw", "raw": ""})]
        )
        draft = parse_postman(col)[0]
        assert draft.body is None
        assert draft.body_kind is BodyKind.NONE


class TestAuth:
    def test_bearer_auth_becomes_authorization_header(self) -> None:
        col = _collection(
            [
                _request_item(
                    "B",
                    method="GET",
                    url="https://x/y",
                    auth={"type": "bearer", "bearer": [{"key": "token", "value": "tok123"}]},
                )
            ]
        )
        assert parse_postman(col)[0].headers["Authorization"] == "Bearer tok123"

    def test_basic_auth_becomes_authorization_header(self) -> None:
        col = _collection(
            [
                _request_item(
                    "B",
                    method="GET",
                    url="https://x/y",
                    auth={
                        "type": "basic",
                        "basic": [
                            {"key": "username", "value": "u"},
                            {"key": "password", "value": "p"},
                        ],
                    },
                )
            ]
        )
        expected = "Basic " + base64.b64encode(b"u:p").decode()
        assert parse_postman(col)[0].headers["Authorization"] == expected

    def test_unsupported_auth_type_warns(self) -> None:
        col = _collection(
            [
                _request_item(
                    "O",
                    method="GET",
                    url="https://x/y",
                    auth={"type": "oauth2", "oauth2": []},
                )
            ]
        )
        draft = parse_postman(col)[0]
        assert "Authorization" not in draft.headers
        assert any("oauth2" in w for w in draft.warnings)


class TestName:
    def test_uses_item_name(self) -> None:
        col = _collection([_request_item("My Request", method="GET", url="https://x/y")])
        assert parse_postman(col)[0].name == "My Request"

    def test_derives_name_when_missing(self) -> None:
        col = _collection([{"request": {"method": "GET", "url": "https://x/health"}}])
        assert parse_postman(col)[0].name == "GET /health"


class TestAcceptanceCriterion:
    """SPEC §7: a 3-request collection (one in a folder, one using a `{{baseUrl}}`
    var) yields 3 drafts with vars resolved; an undefined var produces a warning."""

    def test_three_request_collection(self) -> None:
        col = _collection(
            [
                {
                    "name": "Health",
                    "item": [_request_item("Health check", method="GET", url="{{baseUrl}}/health")],
                },
                _request_item(
                    "Create user",
                    method="POST",
                    url="{{baseUrl}}/users",
                    header=[{"key": "Content-Type", "value": "application/json"}],
                    body={"mode": "raw", "raw": '{"name":"x"}'},
                ),
                _request_item("Get item", method="GET", url="{{baseUrl}}/items/{{itemId}}"),
            ],
            variables=[{"key": "baseUrl", "value": "https://api.example.com"}],
        )
        drafts = parse_postman(col)
        assert len(drafts) == 3
        assert drafts[0].url == "https://api.example.com/health"
        assert drafts[1].url == "https://api.example.com/users"
        assert drafts[1].body_kind is BodyKind.JSON
        assert drafts[2].url == "https://api.example.com/items/{{itemId}}"
        assert drafts[0].warnings == [] and drafts[1].warnings == []
        assert any("itemId" in w for w in drafts[2].warnings)
