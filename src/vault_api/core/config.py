"""Application settings, loaded from `VAULT_`-prefixed environment variables and `.env`."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "VAULT_"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_PORT = 65535


class Settings(BaseSettings):
    """Runtime configuration. Secrets and connection strings have no defaults."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX, env_file=".env", env_file_encoding="utf-8"
    )

    app_name: str = "Secure Credential Vault API"
    debug: bool = False
    sql_echo: bool = False
    database_url: str
    host: str = DEFAULT_HOST
    port: int = Field(default=DEFAULT_PORT, ge=1, le=MAX_PORT)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read once on first use."""
    return Settings()
