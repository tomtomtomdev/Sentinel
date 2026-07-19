"""Unit tests for the S15 rotation helpers in `secret_mapping` (SPEC §6, PLAN D40).

`rotate_*` re-encrypts a stored ciphertext under the ring's *first* key without
ever materializing plaintext (`SecretBox.rotate`). They share the very same
`is_secret_header`/`is_secret_config_key` classifiers as encryption, so which
values are secret can never drift between writing and rotating. No DB, no network.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from sentinel.infrastructure.db.secret_mapping import (
    decrypt_secret_config,
    decrypt_secret_headers,
    decrypt_value,
    encrypt_secret_config,
    encrypt_secret_headers,
    encrypt_value,
    rotate_secret_config,
    rotate_secret_headers,
    rotate_value,
)
from sentinel.infrastructure.secrets import FernetSecretBox


def _key() -> str:
    return Fernet.generate_key().decode()


def test_rotate_value_re_encrypts_under_the_new_first_key() -> None:
    old, new = _key(), _key()
    stored = encrypt_value("s3cret", FernetSecretBox([old]))

    rotated = rotate_value(stored, FernetSecretBox([new, old]))

    assert decrypt_value(rotated, FernetSecretBox([new])) == "s3cret"
    with pytest.raises(InvalidToken):
        decrypt_value(rotated, FernetSecretBox([old]))


def test_rotate_secret_headers_only_touches_secret_values() -> None:
    old, new = _key(), _key()
    stored = encrypt_secret_headers(
        {"Authorization": "Bearer t0ken", "Content-Type": "application/json"},
        FernetSecretBox([old]),
    )

    rotated = rotate_secret_headers(stored, FernetSecretBox([new, old]))

    # Non-secret header passes through verbatim (never was ciphertext).
    assert rotated["Content-Type"] == "application/json"
    # The whole map now decrypts under the new key alone — old key droppable.
    assert decrypt_secret_headers(rotated, FernetSecretBox([new])) == {
        "Authorization": "Bearer t0ken",
        "Content-Type": "application/json",
    }
    with pytest.raises(InvalidToken):
        decrypt_value(rotated["Authorization"], FernetSecretBox([old]))


def test_rotate_secret_config_only_touches_secret_string_values() -> None:
    old, new = _key(), _key()
    stored = encrypt_secret_config({"bot_token": "abc123", "chat_id": "42"}, FernetSecretBox([old]))

    rotated = rotate_secret_config(stored, FernetSecretBox([new, old]))

    assert rotated["chat_id"] == "42"  # non-secret passthrough
    assert decrypt_secret_config(rotated, FernetSecretBox([new])) == {
        "bot_token": "abc123",
        "chat_id": "42",
    }
    with pytest.raises(InvalidToken):
        decrypt_value(rotated["bot_token"], FernetSecretBox([old]))
