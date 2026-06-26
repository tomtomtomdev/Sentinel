"""Pure curl parser (SPEC §3.1, §5, §7 import-curl). Table-driven over many curl
shapes. A curl string is untrusted data — parsed, never executed."""

from __future__ import annotations

import base64

from sentinel.domain.logic.curl_import import parse_curl
from sentinel.domain.value_objects import BodyKind, HttpMethod


class TestBasics:
    def test_bare_url_defaults_to_get(self) -> None:
        draft = parse_curl("curl https://x/y")
        assert draft.method is HttpMethod.GET
        assert draft.url == "https://x/y"
        assert draft.headers == {}
        assert draft.body is None
        assert draft.body_kind is BodyKind.NONE
        assert draft.warnings == []

    def test_name_is_method_and_path(self) -> None:
        assert parse_curl("curl https://x/y").name == "GET /y"
        assert parse_curl("curl https://api.example.com/health").name == "GET /health"

    def test_works_without_leading_curl_token(self) -> None:
        assert parse_curl("https://x/y").url == "https://x/y"

    def test_single_header(self) -> None:
        draft = parse_curl("curl -H 'X-Api-Key: k' https://x/y")
        assert draft.headers == {"X-Api-Key": "k"}
        assert draft.method is HttpMethod.GET
        assert draft.warnings == []


class TestMethodAndBody:
    def test_explicit_method_flag(self) -> None:
        assert parse_curl("curl -X DELETE https://x/y").method is HttpMethod.DELETE

    def test_attached_method_flag(self) -> None:
        assert parse_curl("curl -XPUT https://x/y").method is HttpMethod.PUT

    def test_long_request_flag(self) -> None:
        assert parse_curl("curl --request PATCH https://x/y").method is HttpMethod.PATCH

    def test_data_implies_post_when_no_method(self) -> None:
        draft = parse_curl("curl https://x/y -d 'a=1'")
        assert draft.method is HttpMethod.POST
        assert draft.body == "a=1"

    def test_explicit_method_overrides_data_implied_post(self) -> None:
        assert parse_curl("curl -X PUT https://x/y -d 'a=1'").method is HttpMethod.PUT

    def test_multiple_data_joined_with_ampersand(self) -> None:
        draft = parse_curl("curl https://x/y -d 'a=1' -d 'b=2'")
        assert draft.body == "a=1&b=2"
        assert draft.body_kind is BodyKind.FORM

    def test_unsupported_method_warns_and_defaults_to_get(self) -> None:
        draft = parse_curl("curl -X PURGE https://x/y")
        assert draft.method is HttpMethod.GET
        assert any("PURGE" in w for w in draft.warnings)


class TestBodyKindInference:
    def test_json_body_with_content_type(self) -> None:
        draft = parse_curl(
            "curl -X POST https://x/y -H 'Content-Type: application/json' -d '{\"a\":1}'"
        )
        assert draft.body_kind is BodyKind.JSON
        assert draft.body == '{"a":1}'

    def test_json_inferred_from_shape_without_header(self) -> None:
        assert parse_curl("curl -X POST https://x/y -d '{\"a\":1}'").body_kind is BodyKind.JSON

    def test_form_inferred_from_shape(self) -> None:
        assert parse_curl("curl https://x/y -d 'a=1&b=2'").body_kind is BodyKind.FORM

    def test_form_from_content_type(self) -> None:
        draft = parse_curl(
            "curl https://x/y -H 'Content-Type: application/x-www-form-urlencoded' -d 'token'"
        )
        assert draft.body_kind is BodyKind.FORM

    def test_raw_body(self) -> None:
        assert parse_curl("curl https://x/y -d 'just text'").body_kind is BodyKind.RAW


class TestAcceptanceCriterion:
    """SPEC §7: a curl with method, two headers, and a JSON -d body → one draft
    with those fields and no warnings."""

    def test_representative_curl(self) -> None:
        draft = parse_curl(
            "curl -X POST https://api.example.com/users "
            "-H 'Content-Type: application/json' -H 'Accept: application/json' "
            '-d \'{"name":"x"}\''
        )
        assert draft.method is HttpMethod.POST
        assert draft.url == "https://api.example.com/users"
        assert draft.headers == {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        assert draft.body == '{"name":"x"}'
        assert draft.body_kind is BodyKind.JSON
        assert draft.warnings == []


class TestFlags:
    def test_url_flag(self) -> None:
        assert parse_curl("curl --url https://x/y").url == "https://x/y"

    def test_basic_auth_becomes_authorization_header(self) -> None:
        draft = parse_curl("curl -u alice:secret https://x/y")
        expected = "Basic " + base64.b64encode(b"alice:secret").decode()
        assert draft.headers["Authorization"] == expected

    def test_location_sets_follow_redirects(self) -> None:
        assert parse_curl("curl -L https://x/y").follow_redirects is True
        assert parse_curl("curl https://x/y").follow_redirects is False

    def test_compressed_is_recognized_without_warning(self) -> None:
        assert parse_curl("curl --compressed https://x/y").warnings == []

    def test_unknown_flag_warns_but_still_parses(self) -> None:
        draft = parse_curl("curl --insecure https://x/y")
        assert draft.url == "https://x/y"
        assert any("--insecure" in w for w in draft.warnings)


class TestRobustness:
    def test_multiline_with_backslash_continuations(self) -> None:
        command = "curl https://x/y \\\n  -H 'X-Api-Key: k' \\\n  -d 'a=1'"
        draft = parse_curl(command)
        assert draft.url == "https://x/y"
        assert draft.headers == {"X-Api-Key": "k"}
        assert draft.body == "a=1"

    def test_header_without_colon_warns(self) -> None:
        draft = parse_curl("curl -H 'NoColonHeader' https://x/y")
        assert any("NoColonHeader" in w for w in draft.warnings)

    def test_no_url_warns(self) -> None:
        draft = parse_curl("curl -X GET")
        assert draft.url == ""
        assert any("URL" in w for w in draft.warnings)

    def test_double_quoted_values(self) -> None:
        draft = parse_curl('curl -H "X-Token: a b c" https://x/y')
        assert draft.headers == {"X-Token": "a b c"}
