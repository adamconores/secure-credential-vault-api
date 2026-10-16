"""Async database engine and session management.

The engine is created lazily, so importing this module does not require configuration.
"""

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry, StaticPool

from vault_api.core.config import get_settings

SQLITE_BACKEND = "sqlite"
SQLITE_IN_MEMORY_DATABASES = frozenset({None, "", ":memory:"})


def _enable_sqlite_foreign_keys(
    dbapi_connection: DBAPIConnection, _pool_entry: ConnectionPoolEntry
) -> None:
    """Turn on foreign-key enforcement, which SQLite leaves off per connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def build_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create an async engine with the project's safety settings.

    Bound parameters are never logged, so SQL echo cannot leak hashes or ciphertext.
    SQLite connections enforce foreign keys, and an in-memory SQLite database is shared
    by every session through a single static connection.
    """
    url = make_url(database_url)
    engine_options: dict[str, Any] = {}
    is_sqlite = url.get_backend_name() == SQLITE_BACKEND
    if is_sqlite and url.database in SQLITE_IN_MEMORY_DATABASES:
        engine_options["poolclass"] = StaticPool
        engine_options["connect_args"] = {"check_same_thread": False}

    engine = create_async_engine(url, echo=echo, hide_parameters=True, **engine_options)
    if is_sqlite:
        event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    return engine


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide async engine for the configured database."""
    settings = get_settings()
    return build_engine(settings.database_url, echo=settings.sql_echo)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the factory that opens sessions bound to the shared engine."""
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield one session per request and close it afterwards."""
    async with get_session_factory()() as session:
        yield session
