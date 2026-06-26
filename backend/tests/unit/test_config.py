"""Unit tests for configuration parsing (SPEC §6 — `SECRET_KEY` is a key ring)."""

from __future__ import annotations

from sentinel.config import Settings


def test_secret_key_ring_splits_on_commas_and_strips_whitespace() -> None:
    settings = Settings(secret_key="key-a, key-b ,key-c")
    assert settings.secret_key_ring() == ["key-a", "key-b", "key-c"]


def test_secret_key_ring_is_empty_when_unset() -> None:
    settings = Settings(secret_key="")
    assert settings.secret_key_ring() == []


def test_secret_key_ring_ignores_blank_entries() -> None:
    settings = Settings(secret_key="key-a,,  ,key-b,")
    assert settings.secret_key_ring() == ["key-a", "key-b"]
