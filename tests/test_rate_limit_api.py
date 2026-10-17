from collections.abc import AsyncIterator, Callable

import anyio
import httpx2
import pytest
from conftest import FakeClock
from sqlalchemy.ext.asyncio import AsyncSession

from vault_api.api.rate_limits import (
    LOGIN_FAILURES_PER_EMAIL,
    LOGIN_PER_IP,
    REGISTER_PER_IP,
    TOO_MANY_ATTEMPTS,
)
from vault_api.core.rate_limit import SlidingWindowRateLimiter
from vault_api.main import create_app
from vault_api.services import auth as auth_service

pytestmark = pytest.mark.anyio

LOGIN_URL = "/api/v1/auth/login"
REGISTER_URL = "/api/v1/auth/register"
EMAIL = "owner@example.com"
PASSWORD = "correct horse battery staple"
WRONG_PASSWORD = "wrong password!"
TEST_BASE_URL = "http://testserver"

ClientFactory = Callable[[str], httpx2.AsyncClient]


@pytest.fixture
async def client_from(db_session: AsyncSession, clock: FakeClock) -> AsyncIterator[ClientFactory]:
    """Clients for different source IPs, all talking to one app and one limiter."""
    app = create_app(rate_limiter=SlidingWindowRateLimiter(clock=clock))
    clients: list[httpx2.AsyncClient] = []

    def make(ip: str) -> httpx2.AsyncClient:
        transport = httpx2.ASGITransport(app=app, client=(ip, 50000))
        client = httpx2.AsyncClient(transport=transport, base_url=TEST_BASE_URL)
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


async def login(
    client: httpx2.AsyncClient, email: str = EMAIL, password: str = PASSWORD
) -> httpx2.Response:
    return await client.post(LOGIN_URL, data={"username": email, "password": password})


async def register(client: httpx2.AsyncClient, email: str = EMAIL) -> httpx2.Response:
    return await client.post(REGISTER_URL, json={"email": email, "password": PASSWORD})


def assert_throttled(response: httpx2.Response) -> None:
    assert response.status_code == 429
    assert response.json() == {"detail": TOO_MANY_ATTEMPTS}
    assert int(response.headers["retry-after"]) >= 1


async def test_login_is_limited_per_ip(client_from: ClientFactory) -> None:
    attacker, bystander = client_from("203.0.113.1"), client_from("203.0.113.2")
    await register(bystander)

    for n in range(LOGIN_PER_IP.max_attempts):
        response = await login(attacker, email=f"user{n}@example.com")
        assert response.status_code == 401

    assert_throttled(await login(attacker, email="another@example.com"))
    assert (await login(bystander)).status_code == 200


async def test_failed_logins_are_limited_per_email_across_ips(
    client_from: ClientFactory,
) -> None:
    await register(client_from("198.51.100.1"))

    for n in range(LOGIN_FAILURES_PER_EMAIL.max_attempts):
        response = await login(client_from(f"198.51.100.{10 + n}"), password=WRONG_PASSWORD)
        assert response.status_code == 401

    # Even the correct password is refused while the email is throttled.
    assert_throttled(await login(client_from("198.51.100.99")))


async def test_unknown_email_is_throttled_like_a_registered_one(
    client_from: ClientFactory,
) -> None:
    await register(client_from("192.0.2.1"))
    answers = {}
    for email in (EMAIL, "nobody@example.com"):
        for n in range(LOGIN_FAILURES_PER_EMAIL.max_attempts):
            await login(client_from(f"192.0.2.{10 + n}"), email=email, password=WRONG_PASSWORD)
        answers[email] = await login(client_from("192.0.2.200"), email=email)

    registered, unknown = answers[EMAIL], answers["nobody@example.com"]
    assert registered.status_code == unknown.status_code == 429
    assert registered.json() == unknown.json()


async def test_email_counter_ignores_case_and_whitespace(client_from: ClientFactory) -> None:
    variants = [EMAIL, EMAIL.upper(), f"  {EMAIL}  ", "Owner@Example.COM", EMAIL]
    for n, variant in enumerate(variants):
        await login(client_from(f"192.0.2.{50 + n}"), email=variant, password=WRONG_PASSWORD)

    assert_throttled(await login(client_from("192.0.2.99")))


async def test_successful_login_resets_the_email_counter(client_from: ClientFactory) -> None:
    client = client_from("198.51.100.1")
    await register(client)
    for _ in range(LOGIN_FAILURES_PER_EMAIL.max_attempts - 1):
        await login(client, password=WRONG_PASSWORD)

    assert (await login(client)).status_code == 200

    for _ in range(LOGIN_FAILURES_PER_EMAIL.max_attempts - 1):
        assert (await login(client, password=WRONG_PASSWORD)).status_code == 401


async def test_registration_is_limited_per_ip(client_from: ClientFactory) -> None:
    client = client_from("203.0.113.7")

    for n in range(REGISTER_PER_IP.max_attempts):
        assert (await register(client, f"user{n}@example.com")).status_code == 201

    assert_throttled(await register(client, "one-more@example.com"))
    assert (await register(client_from("203.0.113.8"), "elsewhere@example.com")).status_code == 201


async def test_throttled_logins_do_no_hashing(
    client_from: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = client_from("203.0.113.9")
    for n in range(LOGIN_PER_IP.max_attempts):
        await login(client, email=f"user{n}@example.com")
    hashing_calls: list[str] = []
    monkeypatch.setattr(auth_service, "verify_dummy_password", hashing_calls.append)
    monkeypatch.setattr(auth_service, "verify_password", lambda *args: hashing_calls.append("v"))

    assert_throttled(await login(client))
    assert hashing_calls == []


async def test_limits_lift_after_the_window(client_from: ClientFactory, clock: FakeClock) -> None:
    client = client_from("203.0.113.10")
    await register(client)
    for _ in range(LOGIN_FAILURES_PER_EMAIL.max_attempts):
        await login(client, password=WRONG_PASSWORD)
    throttled = await login(client)
    assert_throttled(throttled)

    clock.advance(int(throttled.headers["retry-after"]))

    assert (await login(client)).status_code == 200


async def test_concurrent_failures_cannot_exceed_the_email_limit(
    client_from: ClientFactory,
) -> None:
    await register(client_from("198.51.100.1"))
    attempts = 3 * LOGIN_FAILURES_PER_EMAIL.max_attempts
    clients = [client_from(f"198.51.100.{10 + n}") for n in range(attempts)]

    responses: list[httpx2.Response] = []

    async def attempt(client: httpx2.AsyncClient) -> None:
        responses.append(await login(client, password=WRONG_PASSWORD))

    async with anyio.create_task_group() as group:
        for client in clients:
            group.start_soon(attempt, client)

    statuses = sorted(response.status_code for response in responses)
    assert statuses.count(401) == LOGIN_FAILURES_PER_EMAIL.max_attempts
    assert statuses.count(429) == attempts - LOGIN_FAILURES_PER_EMAIL.max_attempts


async def test_email_throttled_logins_do_no_hashing(
    client_from: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    for n in range(LOGIN_FAILURES_PER_EMAIL.max_attempts):
        await login(client_from(f"192.0.2.{n + 1}"), password=WRONG_PASSWORD)
    hashing_calls: list[str] = []
    monkeypatch.setattr(auth_service, "verify_dummy_password", hashing_calls.append)
    monkeypatch.setattr(auth_service, "verify_password", lambda *args: hashing_calls.append("v"))

    assert_throttled(await login(client_from("192.0.2.100")))
    assert hashing_calls == []


async def test_retry_after_counts_down_from_the_oldest_failure(
    client_from: ClientFactory, clock: FakeClock
) -> None:
    client = client_from("203.0.113.20")
    await login(client, password=WRONG_PASSWORD)
    clock.advance(100)
    for _ in range(LOGIN_FAILURES_PER_EMAIL.max_attempts - 1):
        await login(client, password=WRONG_PASSWORD)

    response = await login(client)

    expected = int(LOGIN_FAILURES_PER_EMAIL.window_seconds) - 100
    assert response.headers["retry-after"] == str(expected)


@pytest.mark.parametrize(
    ("first", "second", "shared"),
    [
        ("2001:db8:1:2::1", "2001:db8:1:2:ffff::9", True),
        ("2001:db8:1:2::1", "2001:db8:1:3::1", False),
        ("203.0.113.1", "203.0.113.2", False),
    ],
    ids=["same-ipv6-64", "different-ipv6-64", "ipv4-per-address"],
)
async def test_ipv6_clients_are_limited_per_64_prefix(
    client_from: ClientFactory, first: str, second: str, shared: bool
) -> None:
    for n in range(LOGIN_PER_IP.max_attempts):
        await login(client_from(first), email=f"user{n}@example.com")

    response = await login(client_from(second), email="other@example.com")

    assert (response.status_code == 429) is shared
