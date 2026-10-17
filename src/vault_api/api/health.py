"""Liveness and database readiness check for orchestrators and load balancers."""

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from vault_api.api.dependencies import SessionDep

HEALTH_PATH = "/health"
STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get(HEALTH_PATH)
async def health(session: SessionDep, response: Response) -> dict[str, str]:
    """Answer 200 when the database answers a trivial query, 503 otherwise."""
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as error:
        logger.warning("Health check failed: database unreachable (%s)", type(error).__name__)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": STATUS_UNAVAILABLE}
    return {"status": STATUS_OK}
