"""Alembic environment: runs migrations against the database from `Settings`."""

import asyncio
import logging

from alembic import context
from sqlalchemy.engine import Connection

import vault_api.models  # noqa: F401  (registers every table on Base.metadata)
from vault_api.core.config import get_settings
from vault_api.db.base import Base
from vault_api.db.session import build_engine

logging.basicConfig(level=logging.WARNING, format="%(levelname)-5.5s [%(name)s] %(message)s")
logging.getLogger("alembic").setLevel(logging.INFO)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit the migration SQL to stdout without connecting to a database."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run the migrations on an open synchronous connection."""
    # Batch mode rebuilds tables for ALTER operations that SQLite does not support.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Connect with the project's async engine and run the migrations."""
    engine = build_engine(get_settings().database_url)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
