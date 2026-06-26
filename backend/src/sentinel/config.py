from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """12-factor configuration sourced from the environment (PLAN §6).
    Secrets and connection strings never live in code."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://localhost/sentinel"


@lru_cache
def get_settings() -> Settings:
    return Settings()
