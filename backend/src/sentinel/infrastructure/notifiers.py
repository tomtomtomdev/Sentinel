"""Notifier adapters (SPEC §3.7) — the concrete `Notifier` port implementations the
`AlertService` fans out to. A `WebhookNotifier` POSTs the alert as JSON; a
`TelegramNotifier` calls the bot `sendMessage` API; `EmailNotifier` is a parked stub.

Every adapter **never raises**: a channel outage, timeout, or non-2xx status is
classified into a `NotifyResult(ok=False, detail=...)` so it becomes a
`NotificationLog` row, not a crashed check pipeline. The `detail` is a short,
**secret-free** classification (``"HTTP 500"``, the exception class name) — never the
target URL or bot token, which are themselves secrets (SPEC §6). The outbound URL is
otherwise trusted here; the SSRF guard (S10) will wrap these before sending."""

from __future__ import annotations

import httpx

from sentinel.domain.entities import AlertChannel
from sentinel.domain.logic.notify import format_alert_message
from sentinel.domain.value_objects import AlertNotification, NotifyResult

DEFAULT_TIMEOUT_SECONDS = 10.0


def _webhook_payload(notification: AlertNotification) -> dict[str, object | None]:
    """The structured JSON a webhook receives — the secret-free payload fields
    (SPEC §3.7): monitor name, new status, since, last error, and the deep link."""
    n = notification
    return {
        "monitor_id": str(n.monitor_id),
        "monitor": n.monitor_name,
        "status": n.status.value,
        "since": n.since.isoformat(),
        "kind": n.kind.value,
        "error": n.last_error.value if n.last_error else None,
        "deep_link": n.deep_link,
    }


async def _post(
    client: httpx.AsyncClient | None, url: str, *, json: dict[str, object | None]
) -> NotifyResult:
    """POST `json` to `url`, classifying the outcome into a secret-free `NotifyResult`.
    Uses the shared client when given, else opens (and closes) a short-lived one."""
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)
    try:
        response = await client.post(url, json=json)
        # Never include `url` in the detail — a webhook URL can itself carry a secret.
        return NotifyResult(ok=response.is_success, detail=f"HTTP {response.status_code}")
    except Exception as exc:  # a notifier must never raise (SPEC §3.7)
        return NotifyResult(ok=False, detail=type(exc).__name__)
    finally:
        if own_client:
            await client.aclose()


class WebhookNotifier:
    """POSTs the alert payload as JSON to the channel's configured `url`."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def send(self, channel: AlertChannel, notification: AlertNotification) -> NotifyResult:
        url = channel.config.get("url")
        if not isinstance(url, str) or not url:
            return NotifyResult(ok=False, detail="webhook channel missing 'url'")
        return await _post(self._client, url, json=_webhook_payload(notification))


class TelegramNotifier:
    """Sends the rendered message via the Telegram bot `sendMessage` API."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def send(self, channel: AlertChannel, notification: AlertNotification) -> NotifyResult:
        token = channel.config.get("bot_token")
        chat_id = channel.config.get("chat_id")
        if not isinstance(token, str) or not token or not chat_id:
            return NotifyResult(ok=False, detail="telegram channel missing bot_token or chat_id")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        body: dict[str, object | None] = {
            "chat_id": chat_id,
            "text": format_alert_message(notification),
        }
        return await _post(self._client, url, json=body)


class EmailNotifier:
    """Parked stub (SPEC §3.7). SMTP delivery is deferred; an email channel records a
    clear `ok=False` so it is auditable and never crashes the pipeline."""

    async def send(self, channel: AlertChannel, notification: AlertNotification) -> NotifyResult:
        return NotifyResult(ok=False, detail="email notifier not implemented")
