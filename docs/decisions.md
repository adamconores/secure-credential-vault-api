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

## 2026-10-17: Encrypt every user-supplied vault item field, including the name

- **Context:** A vault item holds a name, username, password, URL and notes. Each one leaks information on its own (a URL or name reveals which services a user has accounts with).
- **Decision:** `VaultItem` stores all five as Fernet tokens in `*_encrypted` columns. Only ids, the owner reference and timestamps are plaintext. Models never hold plaintext; encryption happens between the schemas and the models.
- **Alternatives:** Keeping `name` plaintext allows sorting and searching in SQL, but exposes the list of services to anyone with database access.
- **Consequences:** Listing, sorting and searching items happen in the application after decryption, which is cheap at personal-vault scale but rules out SQL-side search.

## 2026-10-17: One server-wide Fernet key, rotatable through MultiFernet

- **Context:** Field encryption needs a key. The options are a server key from the environment or a per-user key derived from the master password.
- **Decision:** One server key (`VAULT_FERNET_KEY`, Phase 3). Phase 3 wraps it in `MultiFernet`, so a new key can be introduced while old tokens still decrypt and are re-encrypted over time.
- **Alternatives:** Keys derived from each user's master password (zero-knowledge) make password reset impossible without losing data and need a key-wrapping scheme; too much complexity for this project's scope.
- **Consequences:** A database dump alone reveals nothing, but the database together with the key reveals everything; the key must be kept out of the repository, logs and the database host's backups. Losing the key loses every stored credential.

## 2026-10-17: UUID4 primary keys and database-generated timestamps

- **Context:** Item and user ids will appear in URLs (`/vault/{id}`).
- **Decision:** Random UUID4 primary keys via a mixin; `created_at`/`updated_at` set by the database (`now()`), timezone-aware.
- **Alternatives:** Integer ids are smaller but enumerable, which turns any access-control bug into a full data leak.
- **Consequences:** Ids reveal neither counts nor order. SQLite stores UUIDs as `CHAR(32)` and drops timezone offsets; the `UTCDateTime` column type attaches UTC on load and refuses naive values on write, so the API always returns offset-aware UTC times. PostgreSQL uses native `UUID` and `TIMESTAMPTZ`. Mappers use `eager_defaults`, so server-generated timestamps come back in the INSERT/UPDATE itself instead of through a lazy load, which async sessions cannot do.

## 2026-10-17: Alembic for schema migrations from the first model

- **Context:** The schema will change across phases, and PostgreSQL will replace SQLite.
- **Decision:** Alembic with the async `pyproject` template (config in `pyproject.toml`, no `alembic.ini`), batch mode for SQLite, and a constraint naming convention on `Base.metadata`. Tests run upgrade and downgrade, run `alembic check` (with `compare_server_default`, it compares tables, columns, types, nullability, indexes, foreign keys and server defaults), and exercise the CHECK constraint and the cascade on the migrated schema, because `alembic check` does not compare CHECK constraints.
- **Alternatives:** `Base.metadata.create_all` cannot evolve an existing database.
- **Consequences:** Every model change needs a reviewed migration. Autogenerate renders defaults for the comparing dialect, so portable expressions are fixed by hand (see `CLAUDE.md`).
