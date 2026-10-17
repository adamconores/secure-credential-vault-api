import secrets
from collections.abc import AsyncIterator, Iterator

import httpx2
import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

import vault_api.models  # noqa: F401  (registers every table on Base.metadata)
from vault_api.core.config import Settings, get_settings
from vault_api.core.security import get_field_cipher
from vault_api.db.base import Base
from vault_api.db.session import get_engine, get_session_factory
from vault_api.main import create_app

IN_MEMORY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
JWT_SECRET_BYTES = 48
TEST_BASE_URL = "http://testserver"


class FakeClock:
    """Monotonic clock that only moves when told to."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def database_url() -> str:
    return IN_MEMORY_DATABASE_URL


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[None]:
    # Keys are generated per test and never written anywhere.
    monkeypatch.setenv("VAULT_DATABASE_URL", database_url)
    monkeypatch.setenv("VAULT_JWT_SECRET_KEY", secrets.token_urlsafe(JWT_SECRET_BYTES))
    monkeypatch.setenv("VAULT_FERNET_KEYS", Fernet.generate_key().decode())
    caches = (get_settings, get_engine, get_session_factory, get_field_cipher)
    for cached in caches:
        cached.cache_clear()
    yield
    for cached in caches:
        cached.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with get_session_factory()() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx2.AsyncClient]:
    """HTTP client on the test's event loop, sharing the in-memory database."""
    transport = httpx2.ASGITransport(app=create_app())
    async with httpx2.AsyncClient(transport=transport, base_url=TEST_BASE_URL) as http_client:
        yield http_client
