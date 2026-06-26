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

    def secret_key_ring(self) -> list[str]:
        """Parse `SECRET_KEY` into an ordered, whitespace-trimmed key ring,
        dropping blank entries. The first key is the active encryption key."""
        return [key.strip() for key in self.secret_key.split(",") if key.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
