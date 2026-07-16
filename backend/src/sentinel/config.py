from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """12-factor configuration sourced from the environment (PLAN §6).
    Secrets and connection strings never live in code."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://localhost/sentinel"
    # Comma-separated Fernet keys (a key ring). The first encrypts; all decrypt,
    # so rotation is prepend-a-key-and-redeploy. Empty until configured; see
    # `.env.example`. Never commit real keys.
    secret_key: str = ""
    # Dead-man's switch: each scheduler cycle pings this URL (e.g. healthchecks.io).
    # Off (no ping) when unset. See PLAN D8 / SPEC §6.
    heartbeat_url: str = ""
    # Scheduler runner tuning. The loop wakes every `poll_seconds` to re-select due
    # monitors; due monitors are probed with at most `max_concurrency` in flight so
    # one hung endpoint can't starve the rest (SPEC §3.3).
    scheduler_poll_seconds: float = 5.0
    scheduler_max_concurrency: int = 50
    # Alerting policy (SPEC §3.7). System-wide tunables for the pure `should_notify`
    # decision (per-monitor overrides are parked). `flap_threshold` transitions within
    # `flap_window_seconds` trip a single flapping summary; `flap_threshold < 2`
    # disables damping. `renotify_after_seconds` (0 = off) rate-limits a repeat alert.
    alert_flap_threshold: int = 5
    alert_flap_window_seconds: int = 600
    alert_renotify_after_seconds: int = 0
    # Base URL of the dashboard, used to build the deep link in an alert (SPEC §3.7).
    # Empty (the default) omits the link. No trailing slash needed.
    dashboard_base_url: str = ""
    # Static API credential (S9a): every /api/v1 route except /health requires
    # `Authorization: Bearer <AUTH_TOKEN>`. Empty disables the gate — dev only;
    # never expose the API without it (PLAN §6).
    auth_token: str = ""

    def secret_key_ring(self) -> list[str]:
        """Parse `SECRET_KEY` into an ordered, whitespace-trimmed key ring,
        dropping blank entries. The first key is the active encryption key."""
        return [key.strip() for key in self.secret_key.split(",") if key.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
