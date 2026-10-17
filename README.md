# Secure Credential Vault API

[![CI](https://github.com/adamconores/secure-credential-vault-api/actions/workflows/ci.yml/badge.svg)](https://github.com/adamconores/secure-credential-vault-api/actions/workflows/ci.yml)

A headless password-manager API built with FastAPI. Users authenticate with short-lived JWT bearer tokens, passwords are hashed with Argon2id, and every stored credential field is encrypted with Fernet before it reaches the database. Each user sees and changes only their own items.

## Quick start (Docker)

Requires Docker with the Compose plugin.

```sh
scripts/generate-compose-secrets.sh   # random keys and database password in compose-secrets/ (git-ignored)
docker compose up --build
```

Open <http://127.0.0.1:8000/docs>, register through `POST /api/v1/auth/register`, then use **Authorize** with your email as the username. The stack runs PostgreSQL and the API, applies database migrations on start, and only listens on `127.0.0.1`. The database container gets only its own credentials, never the API's keys; the API container runs read-only, without Linux capabilities, as a non-root user.

On this local stack, Docker's port publishing can make every client appear with the same address, so the per-client rate limits act as one shared limit; per-account limits are unaffected. To start over with fresh secrets, run `docker compose down --volumes` and delete `compose-secrets/`; stored items are lost with the old key.

## Security design

| Threat | Countermeasure |
|---|---|
| Database dump or stolen backup | Every item field (name, username, password, URL, notes) is stored as a Fernet token (AES-128-CBC with HMAC-SHA256); keys come from the environment, never from the database. Keys rotate through `MultiFernet`. |
| Offline cracking of account passwords | Argon2id (64 MiB, 3 iterations) via pwdlib; outdated hashes are upgraded on login. |
| Online password guessing | Rate limits per client (IPv4 address or IPv6 /64) and per account, checked before any hashing; concurrent requests cannot slip past them. |
| Account enumeration | Unknown email, wrong password and inactive account give the same answer in about the same time (a dummy hash check runs for unknown emails); throttling applies to unregistered emails too. |
| Token forgery or misuse | HS256 fixed in code (no `alg=none`, no algorithm confusion), required `exp`, `iat`, `iss`, `aud` and `sub` claims, 15-minute lifetime. |
| Reading other users' data (IDOR) | Every query is scoped to the token's user; foreign item ids answer 404, exactly like missing ones. |
| Secrets leaking through the API | `Cache-Control: no-store` on every response; validation errors never echo submitted values; decrypted fields are excluded from `repr`; SQL logging never includes bound parameters; configuration errors never print key material. |
| Resource exhaustion | 256 KiB request body limit, at most 4 concurrent Argon2 hashes, bounded rate-limiter memory. |

Every row has tests, including attack scenarios: forged and expired tokens, tampered ciphertext, concurrent guessing, cross-user access, and a check that no plaintext reaches the database. The reasoning behind each choice, with the alternatives considered and the known weaknesses, is in [`docs/decisions.md`](docs/decisions.md).

## API

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
| `GET` | `/health` | 200 when the database answers, 503 otherwise |

Vault endpoints need `Authorization: Bearer <token>`. Login is limited to 10 attempts per minute per client and 5 attempts per 15 minutes per email (a successful login clears the email's count); registration to 5 per hour per client. Exceeding a limit gets 429 with `Retry-After`. Request bodies over 256 KiB get 413.

## Local development without Docker

Requires [uv](https://docs.astral.sh/uv/), which installs the Python version pinned in `.python-version` (3.12).

```sh
uv sync
cp .env.example .env   # then fill in the keys; .env is git-ignored
uv run alembic upgrade head
uv run vault-api
```

All settings carry the `VAULT_` prefix. `VAULT_DATABASE_URL`, `VAULT_JWT_SECRET_KEY` and `VAULT_FERNET_KEYS` are required and have no defaults; `.env.example` shows how to generate the keys. Interactive docs are off unless `VAULT_ENABLE_DOCS=true`. Local development uses SQLite; the Docker stack and CI use PostgreSQL. Back up the Fernet keys: without them, stored credentials cannot be decrypted.

Tests and checks:

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

CI runs these on every pull request, runs the test suite and the migrations against PostgreSQL, starts the Docker stack and exercises it over HTTP, audits dependencies for known vulnerabilities, and scans the history for secrets. Architecture and common pitfalls: [`docs/development.md`](docs/development.md).

## Before production

Rate-limit counters are kept in memory per process: run a single worker, or move them to a shared store such as Redis. Behind a reverse proxy, start Uvicorn with `--forwarded-allow-ips` set to the proxy's address so the real client IP is used.

Not yet implemented: refresh tokens and token revocation, a command that re-encrypts items after a Fernet key rotation, and TLS termination (put the API behind a reverse proxy that terminates TLS). An attacker who knows a user's email can keep that account's login throttled; see `docs/decisions.md`.

## License

MIT, see `LICENSE`.
