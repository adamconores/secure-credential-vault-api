# Development notes

How the code is organized and the mistakes that are easy to make. Design decisions and their reasons are in `decisions.md`.

## Commands

| Task | Command |
|---|---|
| Install | `uv sync` |
| Test | `uv run pytest` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Type check | `uv run mypy` |
| Build | `uv build` |
| Migrate | `uv run alembic upgrade head` |
| Run | `uv run vault-api` |
| Docker stack | `scripts/generate-compose-secrets.sh`, then `docker compose up --build` |

Tests use in-memory SQLite; set `VAULT_TEST_DATABASE_URL` (for example `postgresql+asyncpg://user:password@localhost:5432/vault_test`) to run them against PostgreSQL, as CI does. Every test drops and recreates the tables.

New migration: `uv run alembic revision --autogenerate -m "<change>"`, then review it. Autogenerate renders server defaults in the dialect of the database it compared against, so replace SQLite-only text such as `sa.text("1")` with portable `sa.true()` / `sa.func.now()`.

## Architecture

Layered package in `src/vault_api/`:

- `core/`: `rate_limit.py` (`SlidingWindowRateLimiter`, in-memory, bounded; `RateLimiter` protocol for a shared store later); `config.py` (pydantic-settings, all config from `VAULT_`-prefixed env vars); `security.py` (Argon2id hashing via pwdlib, HS256 access tokens, `FieldCipher` over `MultiFernet`; all synchronous).
- `db/`: `base.py` (declarative base with a constraint naming convention, UUID and timestamp mixins), `session.py` (`build_engine` applies the safety settings; lazily cached engine and session factory, `get_session`).
- `models/`: `User` and `VaultItem`. Every user-supplied `VaultItem` field is a Fernet token in a `*_encrypted` column; assigning a non-`bytes` value through the ORM raises `TypeError`. The guard does not check that the bytes are a Fernet token, and Core `insert()`/`update()` statements bypass it, so all writes go through the service layer. Import `vault_api.models` to register all tables.
- `schemas/`: plaintext Pydantic v2 request/response models. Encryption happens between schemas and models (via `core/security.py`), never inside either.
- `migrations/`: Alembic (async, config in `pyproject.toml` under `[tool.alembic]`); `env.py` takes the URL from `Settings` and runs in batch mode for SQLite.
- `services/`: business logic independent of HTTP (`auth.py`: registration, authentication; `vault.py`: owner-scoped item CRUD and the only place item fields are encrypted and decrypted). Argon2 runs in worker threads behind a dedicated `anyio.CapacityLimiter` (`MAX_CONCURRENT_HASHES`); never call the hashing functions directly from async code.
- `api/`: `paths.py` (URL prefixes), `dependencies.py` (`SessionDep`, `SettingsDep`, `CipherDep`, `CurrentUserDep`), `rate_limits.py` (limit values and the login/register dependencies; the limiter lives on `app.state`), `middleware.py` (`RequestBodyLimitMiddleware`, 256 KiB; `NoStoreMiddleware`, `Cache-Control: no-store` on every response), `v1/` routers mounted under `/api/v1`: `auth.py` (`/auth/register`, `/auth/login`, `/auth/me`) and `vault.py` (`/vault/items` CRUD). `main.py` replaces FastAPI's 422 body with one that drops the submitted `input`.
- `api/health.py`: `GET /health` (database ping) for Compose and load balancers.
- `main.py`: `create_app()` factory, served by Uvicorn with `factory=True`. `/docs`, `/redoc` and `/openapi.json` exist only when docs are enabled in the settings.

Read `decisions.md` before changing the architecture, and add an entry for every new decision.

## Pitfalls

- `Settings` forbids unknown keys from `.env` (pydantic-settings default). Add a field before adding its variable to `.env`.
- SQL echo is a separate setting (`VAULT_SQL_ECHO`), and the engine always uses `hide_parameters=True`; keep both, or hashes and ciphertext end up in logs.
- Always create engines with `build_engine`: it shares one `StaticPool` connection for in-memory SQLite (otherwise each connection gets its own empty database) and turns on SQLite foreign keys, which are off by default.
- `get_settings`, `get_engine`, `get_session_factory` and `get_field_cipher` are cached; the autouse fixture (which also generates throwaway JWT and Fernet keys) in `tests/conftest.py` clears them. Override the `database_url` fixture to point a test module at another database (see `tests/test_migrations.py`).
- Timestamp columns use `UTCDateTime` (refuses naive datetimes) and mappers use `eager_defaults`. Without `eager_defaults`, reading `updated_at` after an UPDATE lazy-loads and raises `MissingGreenlet` under asyncio.
- `ItemUpdate`: use `model_fields_set` to tell "omitted" from "null". Null clears `username`/`url`/`notes` and is rejected for `name`/`password`.
- Every vault query filters on `owner_id`; go through `services/vault.get_item` rather than `session.get(VaultItem, id)`, which ignores ownership. Foreign items answer 404, exactly like missing ones.
- The body limit is sized for the largest valid item sent with every character as a `\uXXXX` surrogate pair (about 160 KB). If you raise a field maximum in `schemas/item.py`, `test_largest_valid_item_fits_under_the_body_limit` tells you whether the limit still fits.
- Rate limits are checked before any hashing, and counted in the same synchronous step (`consume`); never put an `await` between checking and recording, or concurrent requests slip past the limit. Each `RateLimit` has its own store, so limits cannot evict each other's counters. The per-email login counter is keyed by a SHA-256 of the lowercased email (fixed size, no addresses in memory) and counts failures for any email, registered or not; keep it that way, or throttling reveals which accounts exist.
- Rate-limit tests use `create_app(rate_limiter=SlidingWindowRateLimiter(clock=FakeClock()))` and `httpx2.ASGITransport(client=(ip, port))` to simulate source IPs (see `tests/test_rate_limit_api.py`). Helpers shared between test modules go in `tests/conftest.py`; `tests/` is not a package.
- Never return FastAPI's default 422 body: it echoes submitted values, secrets included. `handle_validation_error` in `main.py` keeps only `loc`, `msg` and `type`.
- Timestamps are set in Python (`utc_now`, microseconds) on ORM writes; SQLite's `CURRENT_TIMESTAMP` has one-second resolution and would make "newest first" ambiguous. The server defaults only cover non-ORM writes.
- `StoredItemUnreadableError` (wrong or missing Fernet key) becomes a generic 500 via the handler in `main.py`; the log line carries only the item id. One unreadable item makes the whole list answer 500, on purpose (see `docs/decisions.md`).
- Tests that inspect database error text must match both SQLite and PostgreSQL wording (for example `(?i)foreign key`; constraint names such as `email_lowercase` appear in both). Migration tests stay on a temporary SQLite file; CI checks the migrations on PostgreSQL separately.
- `Settings` uses `hide_input_in_errors=True`; keep it, or a malformed key is printed in the startup error.
- Authentication failures never reveal their reason: login always answers 401 "Incorrect email or password"; token checks always answer 401 "Could not validate credentials" (`credentials_error()`); a missing header gets FastAPI's 401 "Not authenticated". `InvalidAccessTokenError` always carries the constant `INVALID_TOKEN_MESSAGE`; the PyJWT cause is only in `__cause__`. Do not add messages that distinguish unknown email, wrong password or inactive account.
- API tests use `httpx2.AsyncClient` with `ASGITransport` (the `client` fixture), so the app and the in-memory database share one event loop. `TestClient` runs the app in another thread and breaks that.
- Emails are lowercased by `NormalizedEmail` in the schemas, and a database check constraint rejects anything else. Lowercase before every lookup by email.
