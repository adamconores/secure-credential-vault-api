import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sqlite_file(tmp_path: Path) -> Path:
    return tmp_path / "migrations.db"


@pytest.fixture
def database_url(sqlite_file: Path) -> str:
    return f"sqlite+aiosqlite:///{sqlite_file}"


@pytest.fixture
def alembic_config() -> Config:
    return Config(toml_file=PROJECT_ROOT / "pyproject.toml")


def test_upgrade_creates_tables_that_match_models(
    alembic_config: Config, sqlite_file: Path
) -> None:
    command.upgrade(alembic_config, "head")

    engine = create_engine(f"sqlite:///{sqlite_file}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {"users", "vault_items"} <= tables
    # Raises if the models have changes that no migration covers.
    command.check(alembic_config)


def test_downgrade_removes_all_tables(alembic_config: Config, sqlite_file: Path) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    engine = create_engine(f"sqlite:///{sqlite_file}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert tables == {"alembic_version"}


def test_migrated_schema_enforces_constraints(alembic_config: Config, sqlite_file: Path) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(f"sqlite:///{sqlite_file}")
    insert_user = text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'hash')")
    try:
        with engine.connect() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            with pytest.raises(IntegrityError, match="email_lowercase"):
                connection.execute(insert_user, {"id": uuid.uuid4().hex, "email": "A@b.c"})
            connection.rollback()

            owner_id = uuid.uuid4().hex
            connection.execute(insert_user, {"id": owner_id, "email": "a@b.c"})
            connection.execute(
                text(
                    "INSERT INTO vault_items (id, owner_id, name_encrypted, password_encrypted)"
                    " VALUES (:id, :owner_id, x'00', x'00')"
                ),
                {"id": uuid.uuid4().hex, "owner_id": owner_id},
            )
            connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": owner_id})
            remaining = connection.scalar(text("SELECT count(*) FROM vault_items"))
    finally:
        engine.dispose()
    assert remaining == 0
