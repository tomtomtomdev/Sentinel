"""Executable key-rotation runbook (S14.5, SPEC §6, PLAN D39).

These pin the *documented* rotation mechanism end-to-end. The operator sets
`SECRET_KEY="<new>,<old>"`; the app parses that into a key ring
(`Settings.secret_key_ring`) that feeds `FernetSecretBox` (`MultiFernet`). S5a
already proves the crypto in isolation with explicit key lists; here we prove the
`env-string → ring → box` path the README runbook actually instructs — so a
regression in ring parsing or key order (encrypt-with-first) fails the build, not
the operator's live rotation. No DB, no network.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from sentinel.config import Settings
from sentinel.infrastructure.secrets import FernetSecretBox


def _box(secret_key: str) -> FernetSecretBox:
    """Build the SecretBox exactly as the app does: env string → ring → box."""
    return FernetSecretBox(Settings(secret_key=secret_key).secret_key_ring())


def test_prepending_a_new_key_keeps_existing_ciphertext_readable() -> None:
    # A secret was stored under the original key.
    old = Fernet.generate_key().decode()
    stored = _box(old).encrypt("db-password")

    # Runbook step 1: prepend a fresh key, keep the old — `SECRET_KEY=<new>,<old>`.
    new = Fernet.generate_key().decode()
    rotated = _box(f"{new},{old}")

    # Existing ciphertext still decrypts (MultiFernet decrypts with any ring key).
    assert rotated.decrypt(stored) == "db-password"


def test_after_rotation_new_writes_use_the_new_first_key() -> None:
    old = Fernet.generate_key().decode()
    new = Fernet.generate_key().decode()
    rotated = _box(f"{new},{old}")

    fresh = rotated.encrypt("written-after-rotation")

    # The new (first) key alone reads it — proving it did the encrypting ...
    assert _box(new).decrypt(fresh) == "written-after-rotation"
    # ... and the old key alone cannot, so a leaked *old* key can't read new data.
    with pytest.raises(InvalidToken):
        _box(old).decrypt(fresh)


def test_dropping_the_old_key_too_soon_breaks_its_ciphertext() -> None:
    # The hazard the runbook warns about: at-rest data is NOT auto-re-encrypted,
    # so ciphertext written under the old key stays under it. Remove that key from
    # the ring before re-encrypting and the data is unreadable — hence "keep the
    # old key (decrypt-only) until nothing depends on it" (PLAN D39).
    old = Fernet.generate_key().decode()
    stored = _box(old).encrypt("still-encrypted-under-old-key")

    new = Fernet.generate_key().decode()
    old_key_dropped = _box(new)  # rotated AND removed the old key in one step

    with pytest.raises(InvalidToken):
        old_key_dropped.decrypt(stored)
