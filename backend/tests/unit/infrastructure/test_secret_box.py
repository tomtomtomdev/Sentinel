"""Unit tests for the `SecretBox` adapter (SPEC §6, sentinel-security rule 2).

The adapter wraps `cryptography.fernet.MultiFernet`: encrypt with the first key in
the ring, decrypt with any. These are the slice's heart — round-trip,
ciphertext-at-rest, and decrypt-after-rotation — and run with no DB or network.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from sentinel.infrastructure.secrets import FernetSecretBox


def _key() -> str:
    return Fernet.generate_key().decode()


def test_round_trip_returns_the_original_plaintext() -> None:
    box = FernetSecretBox([_key()])
    assert box.decrypt(box.encrypt("s3cret-value")) == "s3cret-value"


def test_ciphertext_does_not_contain_the_plaintext() -> None:
    box = FernetSecretBox([_key()])
    token = box.encrypt("p@ssw0rd")
    assert isinstance(token, bytes)
    assert b"p@ssw0rd" not in token
    assert box.decrypt(token) == "p@ssw0rd"


def test_encryption_is_non_deterministic() -> None:
    box = FernetSecretBox([_key()])
    assert box.encrypt("same") != box.encrypt("same")


def test_empty_plaintext_round_trips() -> None:
    box = FernetSecretBox([_key()])
    assert box.decrypt(box.encrypt("")) == ""


def test_decrypts_ciphertext_written_under_a_rotated_out_key() -> None:
    # Encrypt under the old ring, then rotate: prepend a new key, keep the old.
    old, new = _key(), _key()
    old_box = FernetSecretBox([old])
    token = old_box.encrypt("rotate-me")

    rotated = FernetSecretBox([new, old])
    assert rotated.decrypt(token) == "rotate-me"


def test_encrypts_with_the_first_key_in_the_ring() -> None:
    new, old = _key(), _key()
    ring = FernetSecretBox([new, old])
    token = ring.encrypt("first-key-only")

    # The new (first) key alone can decrypt it...
    assert FernetSecretBox([new]).decrypt(token) == "first-key-only"
    # ...but the old key alone cannot — proving encryption used the first key.
    with pytest.raises(InvalidToken):
        FernetSecretBox([old]).decrypt(token)


def test_empty_key_ring_is_rejected() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        FernetSecretBox([])


def test_rotate_re_encrypts_ciphertext_under_the_first_key() -> None:
    # A value written under the old key, then the ring rotates (new key prepended).
    old, new = _key(), _key()
    token = FernetSecretBox([old]).encrypt("rotate-me")

    rotated = FernetSecretBox([new, old]).rotate(token)

    # After rotation the NEW key alone decrypts it — so the old key is droppable...
    assert FernetSecretBox([new]).decrypt(rotated) == "rotate-me"
    # ...and the old key alone no longer can (nothing left depends on it).
    with pytest.raises(InvalidToken):
        FernetSecretBox([old]).decrypt(rotated)


def test_rotate_preserves_plaintext_under_a_single_key_ring() -> None:
    box = FernetSecretBox([_key()])
    token = box.encrypt("unchanged")
    assert box.decrypt(box.rotate(token)) == "unchanged"
