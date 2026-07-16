"""Notifier adapters (SPEC §3.7) — the webhook + telegram HTTP clients and the
email stub. Driven with `respx` so no real network is hit. A notifier must NEVER
raise (a channel outage becomes `ok=False`, it can't crash the pipeline) and its
`detail` must never leak the target URL, bot token, or any secret config value."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import respx

from sentinel.domain.entities import AlertChannel
from sentinel.domain.value_objects import (
    AlertNotification,
    ChannelType,
    ErrorKind,
    MonitorStatus,
    NotifyKind,
)
from sentinel.infrastructure.notifiers import EmailNotifier, TelegramNotifier, WebhookNotifier

WEBHOOK_URL = "https://hooks.example.com/secret-path-token"
BOT_TOKEN = "12345:super-secret-bot-token"  # noqa: S105 -- test fixture, not a real secret
CHAT_ID = "42"


def _notification() -> AlertNotification:
    return AlertNotification(
        monitor_id=uuid4(),
        monitor_name="Prod API",
        status=MonitorStatus.DOWN,
        since=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
        kind=NotifyKind.TRANSITION,
        last_error=ErrorKind.TIMEOUT,
        deep_link="https://sentinel.example.com/monitors/x",
    )


def _webhook_channel() -> AlertChannel:
    return AlertChannel(name="wh", type=ChannelType.WEBHOOK, config={"url": WEBHOOK_URL})


def _telegram_channel() -> AlertChannel:
    return AlertChannel(
        name="tg",
        type=ChannelType.TELEGRAM,
        config={"bot_token": BOT_TOKEN, "chat_id": CHAT_ID},
    )


@respx.mock
async def test_webhook_posts_json_payload_and_reports_ok_on_2xx() -> None:
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))

    result = await WebhookNotifier().send(_webhook_channel(), _notification())

    assert result.ok is True
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["content-type"].startswith("application/json")
    body = sent.content.decode()
    assert "Prod API" in body and "down" in body


@respx.mock
async def test_webhook_reports_not_ok_on_5xx_without_leaking_url() -> None:
    respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(500))

    result = await WebhookNotifier().send(_webhook_channel(), _notification())

    assert result.ok is False
    assert result.detail == "HTTP 500"
    assert "secret-path-token" not in (result.detail or "")


@respx.mock
async def test_webhook_transport_error_is_classified_never_raised() -> None:
    respx.post(WEBHOOK_URL).mock(side_effect=httpx.ConnectError("boom"))

    result = await WebhookNotifier().send(_webhook_channel(), _notification())

    assert result.ok is False
    assert result.detail  # a classification, e.g. "ConnectError"
    assert WEBHOOK_URL not in (result.detail or "")
    assert "secret-path-token" not in (result.detail or "")


async def test_webhook_missing_url_is_not_ok() -> None:
    channel = AlertChannel(name="wh", type=ChannelType.WEBHOOK, config={})
    result = await WebhookNotifier().send(channel, _notification())
    assert result.ok is False


@respx.mock
async def test_telegram_posts_to_bot_api_with_chat_id_and_text() -> None:
    route = respx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    result = await TelegramNotifier().send(_telegram_channel(), _notification())

    assert result.ok is True
    body = route.calls.last.request.content.decode()
    assert CHAT_ID in body
    assert "Prod API" in body


@respx.mock
async def test_telegram_failure_detail_does_not_leak_bot_token() -> None:
    respx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(401)
    )

    result = await TelegramNotifier().send(_telegram_channel(), _notification())

    assert result.ok is False
    assert BOT_TOKEN not in (result.detail or "")


async def test_telegram_missing_config_is_not_ok() -> None:
    channel = AlertChannel(name="tg", type=ChannelType.TELEGRAM, config={"chat_id": CHAT_ID})
    result = await TelegramNotifier().send(channel, _notification())
    assert result.ok is False


async def test_email_notifier_is_a_parked_stub() -> None:
    channel = AlertChannel(name="mail", type=ChannelType.EMAIL, config={"to": "ops@example.com"})
    result = await EmailNotifier().send(channel, _notification())
    assert result.ok is False
    assert result.detail
