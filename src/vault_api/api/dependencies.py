"""Reusable FastAPI dependencies for the API routers."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from vault_api.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
