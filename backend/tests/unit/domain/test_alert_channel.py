"""S9.2 — `AlertChannel`/`NotificationLog` entities + channel-config redaction
(SPEC §3.7, §4, §6). Config secrets are classified by the same kind of key
heuristic that drives header redaction, so at-rest encryption and API redaction
can never drift."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from sentinel.domain.entities import AlertChannel, NotificationLog
from sentinel.domain.errors import ValidationError
from sentinel.domain.logic.redaction import MASK, is_secret_config_key, redact_config
from sentinel.domain.value_objects import ChannelType, MonitorStatus


class TestIsSecretConfigKey:
    @pytest.mark.parametrize(
        "key",
        ["bot_token", "token", "password", "smtp_password", "client_secret", "api_key", "apiKey"],
    )
    def test_secret_keys(self, key: str) -> None:
        assert is_secret_config_key(key) is True

    @pytest.mark.parametrize(
        "key", ["url", "chat_id", "smtp_host", "port", "from", "to", "use_tls"]
    )
    def test_non_secret_keys(self, key: str) -> None:
        assert is_secret_config_key(key) is False


class TestRedactConfig:
    def test_masks_secret_values_keeps_the_rest(self) -> None:
        config = {"bot_token": "12345:abcdef", "chat_id": "42"}
        assert redact_config(config) == {"bot_token": MASK, "chat_id": "42"}

    def test_non_string_values_pass_through(self) -> None:
        config = {"smtp_host": "mail.example.com", "port": 587, "use_tls": True}
        assert redact_config(config) == config

    def test_does_not_mutate_input(self) -> None:
        original = {"password": "hunter2"}
        redact_config(original)
        assert original == {"password": "hunter2"}

    def test_empty_config(self) -> None:
        assert redact_config({}) == {}


class TestAlertChannelEntity:
    def test_valid_channel_constructs(self) -> None:
        channel = AlertChannel(
            name="ops-webhook",
            type=ChannelType.WEBHOOK,
            config={"url": "https://hooks.example.com/x"},
        )
        assert channel.enabled is True
        assert channel.id is not None

    def test_blank_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AlertChannel(name="  ", type=ChannelType.TELEGRAM, config={})


class TestNotificationLogEntity:
    def test_constructs_with_generated_id(self) -> None:
        entry = NotificationLog(
            channel_id=uuid4(),
            monitor_id=uuid4(),
            transition_to=MonitorStatus.DOWN,
            transition_at=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
            fired_at=datetime(2026, 7, 15, 12, 0, 1, tzinfo=UTC),
            ok=True,
        )
        assert entry.id is not None
        assert entry.detail is None
