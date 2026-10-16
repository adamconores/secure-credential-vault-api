# Decisions

One entry per decision, newest last. An entry is never edited after the fact: a change of mind is a new entry that names the one it replaces.

## 2026-10-17: uv project with a src layout instead of requirements.txt and app/

- **Context:** The project spec lists `requirements.txt` and a top-level `app/` package; Adam's Python standards require uv and `src/<package>/`.
- **Decision:** Dependencies live in `pyproject.toml` with a committed `uv.lock`; the package is `src/vault_api/` with the spec's subpackages (`core`, `api`, `db`, later `models`, `schemas`).
- **Alternatives:** `requirements.txt` gives no lock of transitive dependencies and no dev groups; a flat `app/` lets tests import the source tree instead of the installed package.
- **Consequences:** Reproducible installs and a single tool for env, run and build. Anyone without uv can still export a requirements file with `uv export`.

## 2026-10-17: pwdlib with Argon2 instead of passlib for password hashing

- **Context:** The spec names passlib. It is unmaintained (last release 1.7.4, 2020), and its bcrypt backend no longer detects the version of current bcrypt releases (bcrypt 4.1 removed the `__about__` module passlib reads).
- **Decision:** Phase 3 hashes passwords with `pwdlib[argon2]` (Argon2id).
- **Alternatives:** passlib with an old bcrypt pinned (unmaintained library, frozen dependency); `argon2-cffi` directly (fine, but no built-in path for migrating hash algorithms).
- **Consequences:** A maintained library, a memory-hard algorithm, and the option to rehash on login if parameters change.

## 2026-10-17: All configuration and secrets come from the environment

- **Context:** The API handles signing keys, encryption keys and database URLs; none may be committed.
- **Decision:** `pydantic-settings` reads environment variables and a git-ignored `.env`; every variable carries the `VAULT_` prefix, so generic names such as `HOST`, `PORT` or `DEBUG` exported for other tools are never picked up. Secrets and `VAULT_DATABASE_URL` have no defaults, so a missing value fails at startup. `.env.example` lists every key, with a local SQLite URL and the not-yet-used secrets commented out.
- **Alternatives:** `python-dotenv` alone gives no validation or typing.
- **Consequences:** Misconfiguration fails fast with a validation error. Unknown keys in `.env` are rejected, so fields must exist before their variables.

## 2026-10-17: SQLite through aiosqlite for local development

- **Context:** The spec allows SQLite for local development and PostgreSQL later; the stack is async SQLAlchemy 2.
- **Decision:** Use `sqlite+aiosqlite` now; add `asyncpg` when PostgreSQL is introduced. Only `VAULT_DATABASE_URL` changes.
- **Alternatives:** PostgreSQL from day one requires a running server for every test run.
- **Consequences:** Zero-setup development. SQLite-specific behaviour (type affinity, limited `ALTER TABLE`) must not leak into the models.
