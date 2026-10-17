"""Password hashing, access tokens and field encryption.

Every function here is synchronous. Hashing is CPU-bound by design, so async callers
run it in a worker thread (see `vault_api.services.auth`).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from pwdlib import PasswordHash

from vault_api.core.config import Settings, get_settings

# Fixed in code, never read from a token or config, so `alg=none` and algorithm
# confusion are impossible.
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "secure-credential-vault-api"
JWT_AUDIENCE = "secure-credential-vault-api"
REQUIRED_TOKEN_CLAIMS = ["sub", "iat", "exp", "iss", "aud"]
TEXT_ENCODING = "utf-8"
DUMMY_PASSWORD = "timing-equalization-placeholder"  # noqa: S105  (not a credential)
# Constant, so logging the exception can never reveal why a token failed.
INVALID_TOKEN_MESSAGE = "invalid access token"  # noqa: S105  (not a credential)

_password_hash = PasswordHash.recommended()


class InvalidAccessTokenError(Exception):
    """The access token is missing a claim, expired, forged or malformed.

    The message is always `INVALID_TOKEN_MESSAGE`; the cause is chained as `__cause__`.
    """


class DecryptionError(Exception):
    """A stored token was tampered with or encrypted under an unknown key."""


@dataclass(frozen=True)
class PasswordCheck:
    """Result of a password verification."""

    is_valid: bool
    # A new hash when the stored one uses outdated parameters; store it on success.
    updated_hash: str | None


def hash_password(password: str) -> str:
    """Hash a password with Argon2id."""
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> PasswordCheck:
    """Check a password against its stored hash and report whether to rehash it."""
    is_valid, updated_hash = _password_hash.verify_and_update(password, password_hash)
    return PasswordCheck(is_valid=is_valid, updated_hash=updated_hash)


@lru_cache
def _dummy_password_hash() -> str:
    return hash_password(DUMMY_PASSWORD)


def verify_dummy_password(password: str) -> None:
    """Spend the same time as a real verification, for logins with an unknown email.

    Without it, a fast "no such user" answer reveals which emails are registered.
    """
    _password_hash.verify(password, _dummy_password_hash())


def create_access_token(
    user_id: uuid.UUID, settings: Settings, *, issued_at: datetime | None = None
) -> str:
    """Create a signed, short-lived access token whose subject is the user id."""
    now = issued_at or datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    }
    return jwt.encode(claims, settings.jwt_secret_key.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    """Verify an access token and return the user id it was issued for."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            options={"require": REQUIRED_TOKEN_CLAIMS},
        )
        return uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError) as error:
        raise InvalidAccessTokenError(INVALID_TOKEN_MESSAGE) from error


class FieldCipher:
    """Encrypts text fields with Fernet; the first key encrypts, every key decrypts."""

    def __init__(self, keys: Sequence[bytes]) -> None:
        if not keys:
            msg = "FieldCipher needs at least one key"
            raise ValueError(msg)
        self._fernet = MultiFernet([Fernet(key) for key in keys])

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt text into a Fernet token."""
        return self._fernet.encrypt(plaintext.encode(TEXT_ENCODING))

    def decrypt(self, token: bytes) -> str:
        """Decrypt a Fernet token back into text."""
        try:
            return self._fernet.decrypt(token).decode(TEXT_ENCODING)
        except InvalidToken as error:
            msg = "token is invalid or was encrypted under an unknown key"
            raise DecryptionError(msg) from error


@lru_cache
def get_field_cipher() -> FieldCipher:
    """Return the process-wide cipher built from the configured keys."""
    return FieldCipher(get_settings().fernet_key_list)
