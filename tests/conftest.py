from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import vault_api.models  # noqa: F401  (registers every table on Base.metadata)
from vault_api.core.config import get_settings
from vault_api.db.base import Base
from vault_api.db.session import get_engine, get_session_factory

IN_MEMORY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
def database_url() -> str:
    return IN_MEMORY_DATABASE_URL


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[None]:
    monkeypatch.setenv("VAULT_DATABASE_URL", database_url)
    caches = (get_settings, get_engine, get_session_factory)
    for cached in caches:
        cached.cache_clear()
    yield
    for cached in caches:
        cached.cache_clear()


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
