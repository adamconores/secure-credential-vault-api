# Secure Credential Vault API

A headless password-manager API built with FastAPI. Users authenticate with short-lived JWT bearer tokens, passwords are hashed with Argon2id, and stored credentials are encrypted at rest with Fernet before they reach the database. The project is built in phases: registration, login and token authentication are in place; the vault endpoints follow.

## Requirements

- [uv](https://docs.astral.sh/uv/) (it installs the Python version pinned in `.python-version`, currently 3.12)

## Setup

```sh
uv sync
cp .env.example .env   # then edit .env; it is git-ignored
uv run alembic upgrade head
```

All variables carry the `VAULT_` prefix. `VAULT_DATABASE_URL`, `VAULT_JWT_SECRET_KEY` and `VAULT_FERNET_KEYS` are required and have no defaults; `.env.example` shows how to generate the keys. Back up the Fernet keys: without them, stored credentials cannot be decrypted. Local development uses SQLite through `aiosqlite`.

## Usage

```sh
uv run vault-api
```

The API listens on `127.0.0.1:8000` by default (`VAULT_HOST` and `VAULT_PORT` override it). Interactive docs are at `/docs`; its **Authorize** button logs in with the email as username.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/auth/register` | Create an account (JSON: `email`, `password` of 12–128 characters) |
| `POST` | `/api/v1/auth/login` | OAuth2 password form (`username` = email, `password`); returns a bearer token |
| `GET` | `/api/v1/auth/me` | The account the bearer token belongs to |

## Tests and checks

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

## License

MIT, see `LICENSE`.
