# secure-credential-vault-api

Headless password-manager API (FastAPI, async SQLAlchemy) that stores user credentials encrypted at rest.

## Commands

- Setup: `uv sync`, then Adam creates `.env` from `.env.example` (never create, read or fill `.env`)
- Test: `uv run pytest`
- Lint: `uv run ruff check .`
- Type check: `uv run mypy`
- Format: `uv run ruff format .`
- Build: `uv build`
- Run: `uv run vault-api`
- Migrate: `uv run alembic upgrade head`
- New migration: `uv run alembic revision --autogenerate -m "<change>"`, then review it: autogenerate renders server defaults in the dialect of the database it compared against, so replace SQLite-only text like `sa.text("1")` with portable `sa.true()` / `sa.func.now()`.

## Architecture

Layered package in `src/vault_api/` (the spec's `app/` lives here):

- `core/`: `config.py` (pydantic-settings, all config from `VAULT_`-prefixed env vars); `security.py` (Argon2id hashing via pwdlib, HS256 access tokens, `FieldCipher` over `MultiFernet`; all synchronous).
- `db/`: `base.py` (declarative base with a constraint naming convention, UUID and timestamp mixins), `session.py` (`build_engine` applies the safety settings; lazily cached engine and session factory, `get_session`).
- `models/`: `User` and `VaultItem`. Every user-supplied `VaultItem` field is a Fernet token in a `*_encrypted` column; assigning a non-`bytes` value through the ORM raises `TypeError`. The guard does not check that the bytes are a Fernet token, and Core `insert()`/`update()` statements bypass it, so all writes go through the service layer. Import `vault_api.models` to register all tables.
- `schemas/`: plaintext Pydantic v2 request/response models. Encryption happens between schemas and models (via `core/security.py`), never inside either.
- `migrations/`: Alembic (async, config in `pyproject.toml` under `[tool.alembic]`); `env.py` takes the URL from `Settings` and runs in batch mode for SQLite.
- `services/`: business logic independent of HTTP (`auth.py`: registration, authentication). Argon2 runs in worker threads behind a dedicated `anyio.CapacityLimiter` (`MAX_CONCURRENT_HASHES`); never call the hashing functions directly from async code.
- `api/`: `paths.py` (URL prefixes), `dependencies.py` (`SessionDep`, `SettingsDep`, `CurrentUserDep`), `v1/` routers mounted under `/api/v1`: `auth.py` (`/auth/register`, `/auth/login`, `/auth/me`). Planned: `vault.py` (Phase 4).
- `main.py`: `create_app()` factory, served by Uvicorn with `factory=True`.

Work is strictly sequential: Phase 1 architecture, Phase 2 models, Phase 3 auth and crypto, Phase 4 vault endpoints. Do not start a phase until Adam approves the previous one.

Decisions and their reasons: `docs/decisions.md`. Read it before changing the architecture, and add an entry for every new decision.

## Gotchas

- `Settings` forbids unknown keys from `.env` (pydantic-settings default). Add a field before adding its variable to `.env`.
- SQL echo is a separate setting (`VAULT_SQL_ECHO`), and the engine always uses `hide_parameters=True`; keep both, or hashes and ciphertext end up in logs.
- Always create engines with `build_engine`: it shares one `StaticPool` connection for in-memory SQLite (otherwise each connection gets its own empty database) and turns on SQLite foreign keys, which are off by default.
- `get_settings`, `get_engine`, `get_session_factory` and `get_field_cipher` are cached; the autouse fixture (which also generates throwaway JWT and Fernet keys) in `tests/conftest.py` clears them. Override the `database_url` fixture to point a test module at another database (see `tests/test_migrations.py`).
- Timestamp columns use `UTCDateTime` (refuses naive datetimes) and mappers use `eager_defaults`. Without `eager_defaults`, reading `updated_at` after an UPDATE lazy-loads and raises `MissingGreenlet` under asyncio.
- `ItemUpdate`: use `model_fields_set` to tell "omitted" from "null". Null clears `username`/`url`/`notes` and is rejected for `name`/`password`.
- Phase 4: field lengths are counted in characters, not bytes, and Fernet adds about a third. Add a request-body size limit with the endpoints.
- Model and migration tests match SQLite error text (`FOREIGN KEY`, `email_lowercase`); adjust them when tests move to PostgreSQL.
- `Settings` uses `hide_input_in_errors=True`; keep it, or a malformed key is printed in the startup error.
- Authentication failures never reveal their reason: login always answers 401 "Incorrect email or password"; token checks always answer 401 "Could not validate credentials" (`credentials_error()`); a missing header gets FastAPI's 401 "Not authenticated". `InvalidAccessTokenError` always carries the constant `INVALID_TOKEN_MESSAGE`; the PyJWT cause is only in `__cause__`. Do not add messages that distinguish unknown email, wrong password or inactive account.
- API tests use `httpx2.AsyncClient` with `ASGITransport` (the `client` fixture), so the app and the in-memory database share one event loop. `TestClient` runs the app in another thread and breaks that.
- Emails are lowercased by `NormalizedEmail` in the schemas, and a database check constraint rejects anything else. Lowercase before every lookup by email.
- In the ThinkPad sandbox, uv cannot write `~/.cache/uv`; run it with `UV_CACHE_DIR="$TMPDIR/uv-cache"`.
- The dotenv guard matches command text, so write files that mention .env with Write/Edit, and ask Adam to git add .env.example.
