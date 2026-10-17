import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.fernet import Fernet
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pydantic import SecretStr, ValidationError

from vault_api.core.config import JWT_SECRET_MIN_LENGTH, Settings
from vault_api.core.security import (
    INVALID_TOKEN_MESSAGE,
    JWT_ALGORITHM,
    JWT_AUDIENCE,
    JWT_ISSUER,
    DecryptionError,
    FieldCipher,
    InvalidAccessTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from vault_api.models import VaultItem

PASSWORD = "correct horse battery staple"
WEAK_ARGON2_TIME_COST = 1
WEAK_ARGON2_MEMORY_COST_KIB = 8 * 1024


def test_password_hash_verifies_only_the_original_password() -> None:
    password_hash = hash_password(PASSWORD)

    assert password_hash.startswith("$argon2id$")
    assert verify_password(PASSWORD, password_hash).is_valid
    assert not verify_password("wrong password", password_hash).is_valid


def test_current_hash_needs_no_update() -> None:
    assert verify_password(PASSWORD, hash_password(PASSWORD)).updated_hash is None


def test_outdated_hash_parameters_trigger_rehash() -> None:
    weak_hasher = PasswordHash(
        (Argon2Hasher(time_cost=WEAK_ARGON2_TIME_COST, memory_cost=WEAK_ARGON2_MEMORY_COST_KIB),)
    )
    weak_hash = weak_hasher.hash(PASSWORD)

    check = verify_password(PASSWORD, weak_hash)

    assert check.is_valid
    assert check.updated_hash is not None
    assert verify_password(PASSWORD, check.updated_hash).updated_hash is None


def test_access_token_round_trips_user_id(settings: Settings) -> None:
    user_id = uuid.uuid4()

    assert decode_access_token(create_access_token(user_id, settings), settings) == user_id


def test_expired_access_token_is_rejected(settings: Settings) -> None:
    issued_long_ago = datetime.now(UTC) - timedelta(minutes=settings.access_token_ttl_minutes + 1)
    token = create_access_token(uuid.uuid4(), settings, issued_at=issued_long_ago)

    with pytest.raises(InvalidAccessTokenError) as exc_info:
        decode_access_token(token, settings)

    assert isinstance(exc_info.value.__cause__, jwt.ExpiredSignatureError)


def test_token_signed_with_another_key_is_rejected(settings: Settings) -> None:
    other = settings.model_copy(update={"jwt_secret_key": SecretStr("x" * JWT_SECRET_MIN_LENGTH)})
    token = create_access_token(uuid.uuid4(), other)

    with pytest.raises(InvalidAccessTokenError) as exc_info:
        decode_access_token(token, settings)

    assert isinstance(exc_info.value.__cause__, jwt.InvalidSignatureError)


def _signed_claims(settings: Settings, **overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=1),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    }
    claims.update(overrides)
    return claims


@pytest.mark.parametrize(
    ("overrides", "cause"),
    [
        ({"aud": "another-service"}, jwt.InvalidAudienceError),
        ({"iss": "another-issuer"}, jwt.InvalidIssuerError),
        ({"sub": "not-a-uuid"}, ValueError),
        ({"iat": datetime.now(UTC) + timedelta(hours=1)}, jwt.ImmatureSignatureError),
    ],
    ids=["wrong-audience", "wrong-issuer", "non-uuid-subject", "issued-in-future"],
)
def test_token_with_wrong_claims_is_rejected(
    settings: Settings, overrides: dict[str, object], cause: type[Exception]
) -> None:
    token = jwt.encode(
        _signed_claims(settings, **overrides),
        settings.jwt_secret_key.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(InvalidAccessTokenError) as exc_info:
        decode_access_token(token, settings)

    assert isinstance(exc_info.value.__cause__, cause)


@pytest.mark.parametrize("claim", ["sub", "iat", "exp", "iss", "aud"])
def test_token_missing_a_required_claim_is_rejected(settings: Settings, claim: str) -> None:
    claims = _signed_claims(settings)
    del claims[claim]
    token = jwt.encode(claims, settings.jwt_secret_key.get_secret_value(), algorithm=JWT_ALGORITHM)

    with pytest.raises(InvalidAccessTokenError) as exc_info:
        decode_access_token(token, settings)

    assert isinstance(exc_info.value.__cause__, jwt.MissingRequiredClaimError)


def test_token_error_message_carries_no_details(settings: Settings) -> None:
    with pytest.raises(InvalidAccessTokenError) as exc_info:
        decode_access_token("not-a-jwt", settings)

    assert str(exc_info.value) == INVALID_TOKEN_MESSAGE


def test_unsigned_token_is_rejected(settings: Settings) -> None:
    token = jwt.encode(_signed_claims(settings), key="", algorithm="none")

    with pytest.raises(InvalidAccessTokenError) as exc_info:
        decode_access_token(token, settings)

    assert isinstance(exc_info.value.__cause__, jwt.InvalidAlgorithmError)


def test_field_cipher_round_trips_unicode_text() -> None:
    cipher = FieldCipher([Fernet.generate_key()])
    plaintext = "pässwörd 🔑"

    token = cipher.encrypt(plaintext)

    assert plaintext.encode() not in token
    assert cipher.decrypt(token) == plaintext


def test_field_cipher_decrypts_tokens_from_a_retired_key() -> None:
    old_key, new_key = Fernet.generate_key(), Fernet.generate_key()
    token = FieldCipher([old_key]).encrypt("secret")

    rotated = FieldCipher([new_key, old_key])

    assert rotated.decrypt(token) == "secret"
    assert FieldCipher([new_key]).decrypt(rotated.encrypt("fresh")) == "fresh"


def test_field_cipher_rejects_tampered_and_foreign_tokens() -> None:
    cipher = FieldCipher([Fernet.generate_key()])
    token = bytearray(cipher.encrypt("secret"))
    token[-5] ^= 1

    with pytest.raises(DecryptionError):
        cipher.decrypt(bytes(token))
    with pytest.raises(DecryptionError):
        cipher.decrypt(FieldCipher([Fernet.generate_key()]).encrypt("secret"))


def test_settings_reject_short_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_JWT_SECRET_KEY", "x" * (JWT_SECRET_MIN_LENGTH - 1))

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert exc_info.value.errors()[0]["loc"] == ("jwt_secret_key",)


@pytest.mark.parametrize("raw_keys", ["", " , "], ids=["empty", "blank"])
def test_settings_require_a_fernet_key(monkeypatch: pytest.MonkeyPatch, raw_keys: str) -> None:
    monkeypatch.setenv("VAULT_FERNET_KEYS", raw_keys)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert exc_info.value.errors()[0]["loc"] == ("fernet_keys",)


@pytest.mark.parametrize(
    ("variable", "secret"),
    [
        ("VAULT_FERNET_KEYS", "leaked-key-material-that-is-not-fernet"),
        ("VAULT_JWT_SECRET_KEY", "leaked-short-jwt-secret"),
    ],
    ids=["fernet", "jwt"],
)
def test_invalid_secrets_are_not_echoed_in_errors(
    monkeypatch: pytest.MonkeyPatch, variable: str, secret: str
) -> None:
    monkeypatch.setenv(variable, secret)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert secret not in str(exc_info.value)


def test_settings_parse_multiple_fernet_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    primary, retired = Fernet.generate_key(), Fernet.generate_key()
    monkeypatch.setenv("VAULT_FERNET_KEYS", f"{primary.decode()}, {retired.decode()}")

    assert Settings(_env_file=None).fernet_key_list == [primary, retired]


def test_vault_item_refuses_plaintext_in_encrypted_columns() -> None:
    with pytest.raises(TypeError, match="password_encrypted"):
        VaultItem(password_encrypted="plaintext")
