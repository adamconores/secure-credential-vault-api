"""Application settings, loaded from `VAULT_`-prefixed environment variables and `.env`."""

from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "VAULT_"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_PORT = 65535
JWT_SECRET_MIN_LENGTH = 32
DEFAULT_ACCESS_TOKEN_TTL_MINUTES = 15
MAX_ACCESS_TOKEN_TTL_MINUTES = 24 * 60
FERNET_KEY_SEPARATOR = ","


def split_fernet_keys(raw_keys: str) -> list[bytes]:
    """Split a comma-separated key list, dropping blanks; the first key is the primary."""
    return [key.strip().encode() for key in raw_keys.split(FERNET_KEY_SEPARATOR) if key.strip()]


class Settings(BaseSettings):
    """Runtime configuration. Secrets and connection strings have no defaults."""

    # hide_input_in_errors: a startup validation error must never print a secret value.
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        hide_input_in_errors=True,
    )

    app_name: str = "Secure Credential Vault API"
    debug: bool = False
    sql_echo: bool = False
    database_url: str
    host: str = DEFAULT_HOST
    port: int = Field(default=DEFAULT_PORT, ge=1, le=MAX_PORT)
    jwt_secret_key: SecretStr = Field(min_length=JWT_SECRET_MIN_LENGTH)
    access_token_ttl_minutes: int = Field(
        default=DEFAULT_ACCESS_TOKEN_TTL_MINUTES, ge=1, le=MAX_ACCESS_TOKEN_TTL_MINUTES
    )
    fernet_keys: SecretStr

    @field_validator("fernet_keys")
    @classmethod
    def validate_fernet_keys(cls, value: SecretStr) -> SecretStr:
        """Fail at startup on a missing or malformed key, without echoing any key."""
        keys = split_fernet_keys(value.get_secret_value())
        if not keys:
            msg = "at least one Fernet key is required"
            raise ValueError(msg)
        for position, key in enumerate(keys, start=1):
            try:
                Fernet(key)
            except ValueError:
                msg = f"key {position} is not a valid Fernet key (32 url-safe base64 bytes)"
                raise ValueError(msg) from None
        return value

    @property
    def fernet_key_list(self) -> list[bytes]:
        """The Fernet keys, primary (encrypting) key first."""
        return split_fernet_keys(self.fernet_keys.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read once on first use."""
    return Settings()
