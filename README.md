# Secure Credential Vault API

A headless password-manager API built with FastAPI. Users authenticate with short-lived JWT bearer tokens, passwords are hashed with Argon2id, and stored credentials are encrypted at rest with Fernet before they reach the database. Each user sees and changes only their own items. See *Before production* for what a public deployment still needs.

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
| `POST` | `/api/v1/vault/items` | Store an item (`name`, `password`; optional `username`, `url`, `notes`) |
| `GET` | `/api/v1/vault/items` | Your items, newest first (`limit` 1–200, default 50; `offset`) |
| `GET` | `/api/v1/vault/items/{id}` | One item |
| `PATCH` | `/api/v1/vault/items/{id}` | Change the fields sent; `null` clears `username`, `url` or `notes` |
| `DELETE` | `/api/v1/vault/items/{id}` | Delete an item |

Vault endpoints need `Authorization: Bearer <token>`, and answer 404 for items that do not exist or belong to someone else. Every response, errors included, carries `Cache-Control: no-store`. Validation errors (422) list each field's location and reason but never echo the submitted value. Request bodies over 256 KiB get 413.

## Before production

Login is limited to 10 attempts per minute per client and 5 attempts per 15 minutes per email (a successful login clears the email's count); registration to 5 per hour per client. A client is an IPv4 address or an IPv6 /64 network. Exceeding a limit gets 429 with `Retry-After`. The counters are kept in memory per process: behind a reverse proxy, start Uvicorn with `--forwarded-allow-ips` set to the proxy's address so the real client IP is used, and run a single worker (or move the counters to a shared store).

Not yet implemented, and needed before a public deployment: refresh tokens and token revocation, a PostgreSQL deployment with CI running against it, a command that re-encrypts items after a Fernet key rotation, TLS termination, and hiding `/docs` outside development.

## Development

Architecture, commands and common pitfalls: `docs/development.md`. Design decisions and their trade-offs: `docs/decisions.md`.

## Tests and checks

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

## License

MIT, see `LICENSE`.
