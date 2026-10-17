"""FastAPI application factory and the `vault-api` entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from vault_api.api.middleware import NoStoreMiddleware, RequestBodyLimitMiddleware
from vault_api.api.v1 import api_router
from vault_api.core.config import get_settings
from vault_api.core.rate_limit import RateLimiter, SlidingWindowRateLimiter
from vault_api.db.session import get_engine
from vault_api.services.auth import warm_up_password_hashing
from vault_api.services.vault import StoredItemUnreadableError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Warm up password hashing on startup; release database connections on shutdown."""
    await warm_up_password_hashing()
    yield
    await get_engine().dispose()


async def handle_unreadable_item(_request: Request, error: Exception) -> JSONResponse:
    """Answer a generic 500 and log only the item id, never stored data."""
    item_id = error.item_id if isinstance(error, StoredItemUnreadableError) else None
    logger.error("Vault item %s cannot be decrypted with the configured keys", item_id)
    return JSONResponse(
        {"detail": "Internal server error"}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
    )


async def handle_validation_error(_request: Request, error: Exception) -> JSONResponse:
    """422 listing where and why validation failed, without echoing submitted values.

    FastAPI's default body includes each rejected input, which would send secrets back
    and into client logs.
    """
    errors = error.errors() if isinstance(error, RequestValidationError) else []
    detail = [{"loc": item["loc"], "msg": item["msg"], "type": item["type"]} for item in errors]
    return JSONResponse({"detail": detail}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def create_app(rate_limiter: RateLimiter | None = None) -> FastAPI:
    """Build the application from the current settings.

    Each app gets its own rate limiter unless one is passed in (tests pass one with a
    controllable clock).
    """
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.state.rate_limiter = rate_limiter or SlidingWindowRateLimiter()
    app.add_middleware(RequestBodyLimitMiddleware)
    app.add_middleware(NoStoreMiddleware)
    app.add_exception_handler(StoredItemUnreadableError, handle_unreadable_item)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.include_router(api_router)
    return app


def run() -> None:
    """Serve the application with Uvicorn on the configured host and port."""
    settings = get_settings()
    uvicorn.run("vault_api.main:create_app", factory=True, host=settings.host, port=settings.port)
