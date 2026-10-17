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
- **Consequences:** Every model change needs a reviewed migration. Autogenerate renders defaults for the comparing dialect, so portable expressions are fixed by hand.

## 2026-10-17: Short-lived HS256 access tokens, no refresh tokens or revocation yet

- **Context:** The API needs stateless authentication for a single service that both issues and verifies tokens.
- **Decision:** JWTs signed with HS256 (PyJWT), the algorithm fixed in code. Tokens carry `sub` (user id), `iat`, `exp`, `iss` and `aud`, all required on decode. Lifetime defaults to 15 minutes (`VAULT_ACCESS_TOKEN_TTL_MINUTES`, at most 24 hours). The signing key must be at least 32 characters. Every token failure gives the same 401 and message, and the internal exception carries a constant message, so neither responses nor logs reveal why a token was rejected.
- **Alternatives:** RS256/EdDSA pays off only when other services verify tokens. Refresh tokens and a server-side revocation list add state and endpoints; deferred until a client needs long sessions.
- **Consequences:** Logout is client-side; a stolen token stays valid until it expires, which the short lifetime bounds. Deactivating or deleting a user takes effect on the next request, because every request reloads the user. Changing the signing key logs everyone out.

## 2026-10-17: OAuth2 password form for login; uniform answers for failed logins

- **Context:** Login must work with standard clients and must not reveal which emails are registered.
- **Decision:** `POST /api/v1/auth/login` takes the OAuth2 password form (`username` = email), so FastAPI's `/docs` **Authorize** button works. Unknown email, wrong password and inactive account give the same 401; an unknown email still runs one Argon2 verification against a dummy hash, so all three take about the same time. Credentials no account can have (password over the registration maximum, email over 254 characters or containing NUL) are refused before any query or hashing. Hashing runs in worker threads behind a dedicated limiter of 4 concurrent hashes: each Argon2 hash (pwdlib defaults `m=65536,t=3,p=4`) takes 64 MiB, so an unbounded flood of logins could exhaust memory. Excess requests queue. The dummy hash is computed at startup so the first unknown-email login is not slower. Outdated hashes are upgraded on successful login.
- **Alternatives:** A JSON login body is simpler for custom clients but breaks the `/docs` flow.
- **Consequences:** Registration still reveals whether an email is taken (409); that is inherent to self-service sign-up. Login has no rate limiting yet: the limiter bounds memory, but a flood still delays legitimate logins. Per-IP and per-account throttling is required before a public deployment.

## 2026-10-17: Field encryption keys as a MultiFernet list

- **Context:** The server-wide Fernet key (see the earlier entry) must be rotatable without downtime.
- **Decision:** `VAULT_FERNET_KEYS` is a comma-separated list. The first key encrypts; every key decrypts. Each key is validated at startup, and `Settings` hides input values in validation errors so a malformed key is never printed. Rotation: put a new key first, keep the old ones, re-encrypt existing items (a future maintenance command using `MultiFernet.rotate`), then drop the old key.
- **Alternatives:** A single key cannot be rotated without decrypting and re-encrypting everything at once.
- **Consequences:** Old keys stay in the configuration until every item is re-encrypted. Losing all keys loses all stored credentials.
