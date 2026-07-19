"""Unit tests for the auth-source payload rotators (S15, PLAN D40).

`rotate_auth_request`/`rotate_auth_oauth` re-encrypt an auth source's stored
`request`/`oauth` JSONB — the one place the re-encryptor has to know an
auth source's secret field layout (it mirrors
`auth_source_repository._request_to_json`/`_oauth_to_json`). Pure dict→dict, so
they are tested here with no DB; the full DB walk is covered in
`tests/integration/test_reencrypt.py`.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from sentinel.infrastructure.db.secret_mapping import (
    decrypt_secret_headers,
    decrypt_value,
    encrypt_secret_headers,
    encrypt_value,
)
from sentinel.infrastructure.reencrypt import rotate_auth_oauth, rotate_auth_request
from sentinel.infrastructure.secrets import FernetSecretBox


def _key() -> str:
    return Fernet.generate_key().decode()


def test_rotate_auth_request_re_encrypts_body_and_secret_headers() -> None:
    old, new = _key(), _key()
    old_box = FernetSecretBox([old])
    stored = {
        "method": "POST",
        "url": "https://id.example.com/login",
        "headers": encrypt_secret_headers(
            {"X-Api-Key": "k", "Content-Type": "application/json"}, old_box
        ),
        "query_params": {},
        "body": encrypt_value('{"password":"p"}', old_box),
    }

    rotated = rotate_auth_request(stored, FernetSecretBox([new, old]))

    # Non-secret scalars are untouched.
    assert rotated["url"] == "https://id.example.com/login"
    assert rotated["headers"]["Content-Type"] == "application/json"
    # Body + secret header now read under the new key alone (old key droppable).
    new_box, old_only = FernetSecretBox([new]), FernetSecretBox([old])
    assert decrypt_value(rotated["body"], new_box) == '{"password":"p"}'
    assert decrypt_secret_headers(rotated["headers"], new_box)["X-Api-Key"] == "k"
    with pytest.raises(InvalidToken):
        decrypt_value(rotated["body"], old_only)


def test_rotate_auth_request_tolerates_absent_body() -> None:
    old, new = _key(), _key()
    stored = {
        "method": "GET",
        "url": "https://id.example.com/login",
        "headers": encrypt_secret_headers({"X-Api-Key": "k"}, FernetSecretBox([old])),
        "query_params": {},
        "body": None,
    }

    rotated = rotate_auth_request(stored, FernetSecretBox([new, old]))

    assert rotated["body"] is None
    assert decrypt_secret_headers(rotated["headers"], FernetSecretBox([new]))["X-Api-Key"] == "k"


def test_rotate_auth_oauth_re_encrypts_only_present_secrets() -> None:
    old, new = _key(), _key()
    old_box = FernetSecretBox([old])
    stored = {
        "token_url": "https://id.example.com/token",
        "client_id": "cid",
        "client_secret": encrypt_value("super-secret", old_box),
        "scope": "read",
        "client_auth": "basic",
        "username": None,
        "password": None,
    }

    rotated = rotate_auth_oauth(stored, FernetSecretBox([new, old]))

    assert rotated["client_id"] == "cid"  # non-secret passthrough
    assert rotated["username"] is None  # absent secret stays absent
    assert decrypt_value(rotated["client_secret"], FernetSecretBox([new])) == "super-secret"
    with pytest.raises(InvalidToken):
        decrypt_value(rotated["client_secret"], FernetSecretBox([old]))
