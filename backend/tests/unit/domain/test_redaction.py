"""SPEC §6 / sentinel-security: secret-bearing header values are masked at the
serialization boundary. `redact` is the single pure helper that does it."""

from sentinel.domain.logic.redaction import MASK, redact


class TestRedactSecretHeaders:
    def test_authorization_preserves_scheme_masks_credential(self) -> None:
        assert redact({"Authorization": "Bearer s"}) == {"Authorization": f"Bearer {MASK}"}

    def test_basic_authorization_preserves_scheme(self) -> None:
        assert redact({"Authorization": "Basic dXk="}) == {"Authorization": f"Basic {MASK}"}

    def test_proxy_authorization_preserves_scheme(self) -> None:
        result = redact({"Proxy-Authorization": "Bearer t"})
        assert result == {"Proxy-Authorization": f"Bearer {MASK}"}

    def test_authorization_without_scheme_fully_masked(self) -> None:
        assert redact({"Authorization": "rawtokennospace"}) == {"Authorization": MASK}

    def test_named_secret_headers_fully_masked(self) -> None:
        headers = {
            "X-Api-Key": "k",
            "X-Auth-Token": "t",
            "Cookie": "session=abc",
            "Set-Cookie": "session=abc; Path=/",
        }
        assert redact(headers) == {
            "X-Api-Key": MASK,
            "X-Auth-Token": MASK,
            "Cookie": MASK,
            "Set-Cookie": MASK,
        }

    def test_name_matching_is_case_insensitive(self) -> None:
        assert redact({"authorization": "Bearer x"}) == {"authorization": f"Bearer {MASK}"}
        assert redact({"x-api-key": "k"}) == {"x-api-key": MASK}

    def test_heuristic_token_secret_key_substrings_masked(self) -> None:
        headers = {"X-Custom-Token": "a", "My-Secret-Header": "b", "Some-Key-Id": "c"}
        assert redact(headers) == {
            "X-Custom-Token": MASK,
            "My-Secret-Header": MASK,
            "Some-Key-Id": MASK,
        }


class TestRedactKeepsNonSecrets:
    def test_non_secret_headers_pass_through_unchanged(self) -> None:
        headers = {"Content-Type": "application/json", "Accept": "*/*"}
        assert redact(headers) == headers

    def test_mixed_redacts_only_secrets(self) -> None:
        result = redact({"Authorization": "Bearer s", "Content-Type": "application/json"})
        assert result == {"Authorization": f"Bearer {MASK}", "Content-Type": "application/json"}

    def test_empty_headers(self) -> None:
        assert redact({}) == {}

    def test_does_not_mutate_input(self) -> None:
        original = {"Authorization": "Bearer secret"}
        redact(original)
        assert original == {"Authorization": "Bearer secret"}
