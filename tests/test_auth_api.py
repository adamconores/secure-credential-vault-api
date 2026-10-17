from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vault_api.core.config import Settings
from vault_api.core.security import (
    PasswordCheck,
    create_access_token,
    verify_dummy_password,
    verify_password,
)
from vault_api.models import User
from vault_api.services import auth as auth_service

pytestmark = pytest.mark.anyio

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"
EMAIL = "owner@example.com"
PASSWORD = "correct horse battery staple"


async def register(client: httpx2.AsyncClient, email: str = EMAIL) -> httpx2.Response:
    return await client.post(REGISTER_URL, json={"email": email, "password": PASSWORD})


async def login(
    client: httpx2.AsyncClient, email: str = EMAIL, password: str = PASSWORD
) -> httpx2.Response:
    return await client.post(LOGIN_URL, data={"username": email, "password": password})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_register_login_and_read_current_user(
    client: httpx2.AsyncClient, settings: Settings
) -> None:
    registered = await register(client, "Owner@Example.com")
    assert registered.status_code == 201
    assert registered.json()["email"] == EMAIL
    assert "password_hash" not in registered.json()

    token_response = await login(client, "OWNER@example.com")
    assert token_response.status_code == 200
    token = token_response.json()
    assert token["token_type"] == "bearer"
    assert token["expires_in"] == settings.access_token_ttl_minutes * 60

    me = await client.get(ME_URL, headers=bearer(token["access_token"]))
    assert me.status_code == 200
    assert me.json() == registered.json()


async def test_stored_password_is_an_argon2_hash(
    client: httpx2.AsyncClient, db_session: AsyncSession
) -> None:
    await register(client)

    stored = await db_session.scalar(select(User.password_hash))

    assert stored is not None
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored


async def test_duplicate_email_is_rejected_case_insensitively(client: httpx2.AsyncClient) -> None:
    await register(client)

    response = await register(client, EMAIL.upper())

    assert response.status_code == 409


async def test_wrong_password_and_unknown_email_get_identical_answers(
    client: httpx2.AsyncClient,
) -> None:
    await register(client)

    wrong_password = await login(client, password="wrong password!")
    unknown_email = await login(client, email="nobody@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.headers["www-authenticate"] == "Bearer"


@pytest.fixture
def hashing_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every password verification the login path performs."""
    calls: list[str] = []
    real_verify, real_dummy = verify_password, verify_dummy_password

    def recording_verify(password: str, password_hash: str) -> PasswordCheck:
        calls.append("verify")
        return real_verify(password, password_hash)

    def recording_dummy(password: str) -> None:
        calls.append("dummy")
        real_dummy(password)

    monkeypatch.setattr(auth_service, "verify_password", recording_verify)
    monkeypatch.setattr(auth_service, "verify_dummy_password", recording_dummy)
    return calls


@pytest.mark.parametrize(
    ("email", "password"),
    [
        (EMAIL, "x" * 10_000),
        ("x" * 10_000 + "@example.com", PASSWORD),
        ("owner\x00@example.com", PASSWORD),
    ],
    ids=["overlong-password", "overlong-username", "nul-in-username"],
)
async def test_malformed_credentials_are_refused_without_hashing(
    client: httpx2.AsyncClient, hashing_calls: list[str], email: str, password: str
) -> None:
    await register(client)

    response = await login(client, email=email, password=password)

    assert response.status_code == 401
    assert hashing_calls == []


async def test_each_failed_login_runs_exactly_one_verification(
    client: httpx2.AsyncClient, hashing_calls: list[str]
) -> None:
    await register(client)

    await login(client, password="wrong password!")
    await login(client, email="nobody@example.com")

    assert hashing_calls == ["verify", "dummy"]


async def test_login_upgrades_an_outdated_password_hash(
    client: httpx2.AsyncClient, db_session: AsyncSession
) -> None:
    await register(client)
    user = await db_session.scalar(select(User))
    assert user is not None
    weak_hasher = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8 * 1024),))
    user.password_hash = weak_hasher.hash(PASSWORD)
    await db_session.commit()

    assert (await login(client)).status_code == 200

    await db_session.refresh(user)
    assert verify_password(PASSWORD, user.password_hash).updated_hash is None


async def test_registration_race_is_reported_as_conflict(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await register(client)

    async def lookup_misses(session: AsyncSession, email: str) -> None:
        return None

    monkeypatch.setattr(auth_service, "get_user_by_email", lookup_misses)

    assert (await register(client)).status_code == 409


async def test_inactive_user_cannot_log_in_or_use_a_token(
    client: httpx2.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    await register(client)
    user = await db_session.scalar(select(User))
    assert user is not None
    token = create_access_token(user.id, settings)
    user.is_active = False
    await db_session.commit()

    assert (await login(client)).status_code == 401
    assert (await client.get(ME_URL, headers=bearer(token))).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-jwt"}, {"Authorization": "Basic dXNlcjpwYXNz"}],
    ids=["missing", "garbage", "wrong-scheme"],
)
async def test_requests_without_a_valid_token_are_unauthorized(
    client: httpx2.AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.get(ME_URL, headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_expired_token_is_unauthorized(
    client: httpx2.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    await register(client)
    user = await db_session.scalar(select(User))
    assert user is not None
    issued_long_ago = datetime.now(UTC) - timedelta(minutes=settings.access_token_ttl_minutes + 1)
    token = create_access_token(user.id, settings, issued_at=issued_long_ago)

    assert (await client.get(ME_URL, headers=bearer(token))).status_code == 401


async def test_token_for_deleted_user_is_unauthorized(
    client: httpx2.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    await register(client)
    user = await db_session.scalar(select(User))
    assert user is not None
    token = create_access_token(user.id, settings)
    await db_session.delete(user)
    await db_session.commit()

    assert (await client.get(ME_URL, headers=bearer(token))).status_code == 401
