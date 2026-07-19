"""Shared at-rest encryption helpers for the SQL repositories (SPEC §6). Secret
values are stored as Fernet tokens — ASCII base64 strings — in JSONB columns, so
they round-trip as plain strings. Which header names are secret is decided by the
single `is_secret_header` classifier, the same one that drives API redaction, so
encryption and redaction can never drift (PLAN D18)."""

from __future__ import annotations

from typing import Any

from sentinel.domain.logic.redaction import is_secret_config_key, is_secret_header
from sentinel.domain.ports import SecretBox


def encrypt_value(value: str, secret_box: SecretBox) -> str:
    """Encrypt a single secret value to its ASCII Fernet-token string."""
    return secret_box.encrypt(value).decode("ascii")


def decrypt_value(token: str, secret_box: SecretBox) -> str:
    """Inverse of `encrypt_value`."""
    return secret_box.decrypt(token.encode("ascii"))


def encrypt_secret_headers(headers: dict[str, str], secret_box: SecretBox) -> dict[str, str]:
    """Encrypt secret-bearing header values for storage; pass others through."""
    return {
        name: (encrypt_value(value, secret_box) if is_secret_header(name) else value)
        for name, value in headers.items()
    }


def decrypt_secret_headers(headers: dict[str, str], secret_box: SecretBox) -> dict[str, str]:
    """Inverse of `encrypt_secret_headers` — decrypt secret values on read."""
    return {
        name: (decrypt_value(value, secret_box) if is_secret_header(name) else value)
        for name, value in headers.items()
    }


def encrypt_secret_config(config: dict[str, Any], secret_box: SecretBox) -> dict[str, Any]:
    """Encrypt an alert channel's secret (string) config values for storage; pass
    every other value through. Which keys are secret is the shared
    `is_secret_config_key` classifier, so encryption and API redaction never drift."""
    return {
        key: (
            encrypt_value(value, secret_box)
            if is_secret_config_key(key) and isinstance(value, str)
            else value
        )
        for key, value in config.items()
    }


def decrypt_secret_config(config: dict[str, Any], secret_box: SecretBox) -> dict[str, Any]:
    """Inverse of `encrypt_secret_config` — decrypt secret values on read."""
    return {
        key: (
            decrypt_value(value, secret_box)
            if is_secret_config_key(key) and isinstance(value, str)
            else value
        )
        for key, value in config.items()
    }


def rotate_value(token: str, secret_box: SecretBox) -> str:
    """Re-encrypt a single stored ciphertext onto the ring's first key (S15, PLAN
    D40). Never materializes plaintext — see `SecretBox.rotate`."""
    return secret_box.rotate(token.encode("ascii")).decode("ascii")


def rotate_secret_headers(headers: dict[str, str], secret_box: SecretBox) -> dict[str, str]:
    """Rotate secret-bearing header values onto the first key; pass others through.
    Same `is_secret_header` classifier as encryption, so the two never drift."""
    return {
        name: (rotate_value(value, secret_box) if is_secret_header(name) else value)
        for name, value in headers.items()
    }


def rotate_secret_config(config: dict[str, Any], secret_box: SecretBox) -> dict[str, Any]:
    """Rotate an alert channel's secret (string) config values onto the first key;
    pass every other value through. Same `is_secret_config_key` classifier as
    encryption, so the two never drift."""
    return {
        key: (
            rotate_value(value, secret_box)
            if is_secret_config_key(key) and isinstance(value, str)
            else value
        )
        for key, value in config.items()
    }
