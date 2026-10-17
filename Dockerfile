# syntax=docker/dockerfile:1
# Build: the project and its dependencies into /app/.venv with uv.
# Run: a slim image without uv or sources, as a non-root user.
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.14-slim
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
# Root owns the venv and migrations; the app user can read them but not change them.
COPY --from=build /app/.venv ./.venv
COPY pyproject.toml ./
COPY migrations ./migrations
ENV PATH="/app/.venv/bin:${PATH}" PYTHONUNBUFFERED=1 VAULT_HOST=0.0.0.0
USER app
EXPOSE 8000
CMD ["vault-api"]
