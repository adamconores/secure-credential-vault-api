"""FastAPI application factory and the `vault-api` entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from vault_api.core.config import get_settings
from vault_api.db.session import get_engine


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Release pooled database connections when the application shuts down."""
    yield
    await get_engine().dispose()


def create_app() -> FastAPI:
    """Build the application from the current settings."""
    settings = get_settings()
    return FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)


def run() -> None:
    """Serve the application with Uvicorn on the configured host and port."""
    settings = get_settings()
    uvicorn.run("vault_api.main:create_app", factory=True, host=settings.host, port=settings.port)
