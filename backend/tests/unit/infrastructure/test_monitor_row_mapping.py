"""DB-free unit tests for the monitor repository's at-rest encryption mapping.

Proves that secret-bearing header values are encrypted on the way to a row and
decrypted on the way back to an entity, while non-secret headers pass through
untouched. The same secret-name classifier drives both redaction and encryption
(one source of truth — `is_secret_header`).
"""

from __future__ import annotations

from cryptography.fernet import Fernet

from sentinel.infrastructure.db.monitor_repository import _decrypt_headers, _encrypt_headers
from sentinel.infrastructure.secrets import FernetSecretBox


def _box() -> FernetSecretBox:
    return FernetSecretBox([Fernet.generate_key().decode()])


def test_encrypt_headers_ciphers_secret_values_and_passes_others_through() -> None:
    box = _box()
    headers = {"Authorization": "Bearer t", "X-Api-Key": "k", "Accept": "application/json"}

    encrypted = _encrypt_headers(headers, box)

    # Secret values are no longer their plaintext...
    assert encrypted["Authorization"] != "Bearer t"
    assert encrypted["X-Api-Key"] != "k"
    # ...and decrypt back to the original.
    assert box.decrypt(encrypted["Authorization"].encode("ascii")) == "Bearer t"
    assert box.decrypt(encrypted["X-Api-Key"].encode("ascii")) == "k"
    # Non-secret headers are untouched.
    assert encrypted["Accept"] == "application/json"


def test_encrypt_then_decrypt_round_trips_all_headers() -> None:
    box = _box()
    headers = {"Authorization": "Bearer t", "X-Api-Key": "k", "Accept": "application/json"}

    restored = _decrypt_headers(_encrypt_headers(headers, box), box)

    assert restored == headers


def test_empty_headers_round_trip() -> None:
    box = _box()
    assert _decrypt_headers(_encrypt_headers({}, box), box) == {}
