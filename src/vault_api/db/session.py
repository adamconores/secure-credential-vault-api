"""Async database engine and session management.

The engine is created lazily, so importing this module does not require configuration.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from vault_api.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide async engine for the configured database.

    Bound parameters are never logged, so SQL echo cannot leak hashes or ciphertext.
    """
    settings = get_settings()
    return create_async_engine(settings.database_url, echo=settings.sql_echo, hide_parameters=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the factory that opens sessions bound to the shared engine."""
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield one session per request and close it afterwards."""
    async with get_session_factory()() as session:
        yield session
