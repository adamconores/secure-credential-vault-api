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

## Architecture

Layered package in `src/vault_api/` (the spec's `app/` lives here):

- `core/`: `config.py` (pydantic-settings, all config from `VAULT_`-prefixed env vars); `security.py` (hashing, JWT, Fernet) arrives in Phase 3.
- `db/`: `base.py` (declarative base), `session.py` (lazily created async engine and session factory, `get_session`).
- `models/` (SQLAlchemy) and `schemas/` (Pydantic v2): Phase 2.
- `api/`: `dependencies.py` (`SessionDep`; `get_current_user` in Phase 3), routers in `api/v1/` (`auth.py`, `vault.py`).
- `main.py`: `create_app()` factory, served by Uvicorn with `factory=True`.

Work is strictly sequential: Phase 1 architecture, Phase 2 models, then endpoints. Do not start a phase until Adam approves the previous one.

Decisions and their reasons: `docs/decisions.md`. Read it before changing the architecture, and add an entry for every new decision.

## Gotchas

- `Settings` forbids unknown keys from `.env` (pydantic-settings default). Add a field before adding its variable to `.env`.
- SQL echo is a separate setting (`VAULT_SQL_ECHO`), and the engine always uses `hide_parameters=True`; keep both, or hashes and ciphertext end up in logs.
- Phase 2: an in-memory SQLite URL gives every pooled connection its own empty database. DB tests need `StaticPool` (with `check_same_thread=False`) or a temp-file database. SQLite also ignores foreign keys unless a `connect` event runs `PRAGMA foreign_keys=ON`.
- `get_settings`, `get_engine` and `get_session_factory` are cached; tests must clear them (see `tests/test_smoke.py`).
- In the ThinkPad sandbox, uv cannot write `~/.cache/uv`; run it with `UV_CACHE_DIR="$TMPDIR/uv-cache"`.
