"""`SecretBox` adapter — encryption at rest (SPEC §6, sentinel-security rule 2).

Wraps `cryptography.fernet.MultiFernet` so secrets persist encrypted and key
rotation is a config change: build the ring from `SECRET_KEY` (a comma-separated
list of Fernet keys), **encrypt with the first key, decrypt with any**. To rotate,
prepend a fresh key and redeploy — existing ciphertext still decrypts; drop the
old key once nothing depends on it. Keys come from the environment via
`config.py`; never from the repo.
"""

from __future__ import annotations

from collections.abc import Sequence

from cryptography.fernet import Fernet, MultiFernet


class FernetSecretBox:
    """`SecretBox` backed by `MultiFernet`. The first key encrypts; any key in the
    ring can decrypt, which is what makes `SECRET_KEY` rotation non-breaking."""

    def __init__(self, keys: Sequence[str]) -> None:
        if not keys:
            raise ValueError("SecretBox requires at least one key — set SECRET_KEY")
        self._fernet = MultiFernet([Fernet(key) for key in keys])

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        return self._fernet.decrypt(token).decode("utf-8")
