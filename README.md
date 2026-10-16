# Secure Credential Vault API

A headless password-manager API built with FastAPI. Users will authenticate with JWTs, and stored credentials will be encrypted at rest with Fernet before they reach the database. The project is built in phases: this revision contains the architecture (settings, async database session, application factory), the database models with their Alembic migration, and the Pydantic schemas; authentication and the vault endpoints follow.

## Requirements

- [uv](https://docs.astral.sh/uv/) (it installs the Python version pinned in `.python-version`, currently 3.12)

## Setup

```sh
uv sync
cp .env.example .env   # then edit .env; it is git-ignored
uv run alembic upgrade head
```

All variables carry the `VAULT_` prefix. `VAULT_DATABASE_URL` is required and has no default. Local development uses SQLite through `aiosqlite`.

## Usage

```sh
uv run vault-api
```

The API listens on `127.0.0.1:8000` by default (`VAULT_HOST` and `VAULT_PORT` override it). Interactive docs are at `/docs`.

## Tests and checks

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

## License

MIT, see `LICENSE`.
