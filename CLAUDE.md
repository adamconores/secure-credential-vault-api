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

- `core/`: `config.py` (pydantic-settings, all config from `VAULT_`-prefixed env vars); `security.py` (hashing, JWT, Fernet) arrives in Phase 3.
- `db/`: `base.py` (declarative base with a constraint naming convention, UUID and timestamp mixins), `session.py` (`build_engine` applies the safety settings; lazily cached engine and session factory, `get_session`).
- `models/`: `User` and `VaultItem`. Every user-supplied `VaultItem` field is a Fernet token in a `*_encrypted` column; models must never hold plaintext secrets (a convention; nothing enforces it yet). Import `vault_api.models` to register all tables.
- `schemas/`: plaintext Pydantic v2 request/response models. Encryption happens between schemas and models (Phase 3 `core/security.py`), never inside either.
- `migrations/`: Alembic (async, config in `pyproject.toml` under `[tool.alembic]`); `env.py` takes the URL from `Settings` and runs in batch mode for SQLite.
- `api/`: `dependencies.py` (`SessionDep`). Planned: `get_current_user` (Phase 3) and routers in `api/v1/` (`auth.py`, `vault.py`).
- `main.py`: `create_app()` factory, served by Uvicorn with `factory=True`.

Work is strictly sequential: Phase 1 architecture, Phase 2 models, then endpoints. Do not start a phase until Adam approves the previous one.

Decisions and their reasons: `docs/decisions.md`. Read it before changing the architecture, and add an entry for every new decision.

## Gotchas

- `Settings` forbids unknown keys from `.env` (pydantic-settings default). Add a field before adding its variable to `.env`.
- SQL echo is a separate setting (`VAULT_SQL_ECHO`), and the engine always uses `hide_parameters=True`; keep both, or hashes and ciphertext end up in logs.
- Always create engines with `build_engine`: it shares one `StaticPool` connection for in-memory SQLite (otherwise each connection gets its own empty database) and turns on SQLite foreign keys, which are off by default.
- `get_settings`, `get_engine` and `get_session_factory` are cached; the autouse fixture in `tests/conftest.py` clears them. Override the `database_url` fixture to point a test module at another database (see `tests/test_migrations.py`).
- Timestamp columns use `UTCDateTime` (refuses naive datetimes) and mappers use `eager_defaults`. Without `eager_defaults`, reading `updated_at` after an UPDATE lazy-loads and raises `MissingGreenlet` under asyncio.
- `ItemUpdate`: use `model_fields_set` to tell "omitted" from "null". Null clears `username`/`url`/`notes` and is rejected for `name`/`password`.
- Phase 4: field lengths are counted in characters, not bytes, and Fernet adds about a third. Add a request-body size limit with the endpoints.
- Model and migration tests match SQLite error text (`FOREIGN KEY`, `email_lowercase`); adjust them when tests move to PostgreSQL.
- Emails are lowercased by `NormalizedEmail` in the schemas, and a database check constraint rejects anything else. Lowercase before every lookup by email.
- In the ThinkPad sandbox, uv cannot write `~/.cache/uv`; run it with `UV_CACHE_DIR="$TMPDIR/uv-cache"`.
- The dotenv guard matches command text, so write files that mention .env with Write/Edit, and ask Adam to git add .env.example.
