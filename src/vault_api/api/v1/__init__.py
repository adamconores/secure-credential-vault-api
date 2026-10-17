"""Version 1 of the HTTP API."""

from fastapi import APIRouter

from vault_api.api.paths import API_V1_PREFIX
from vault_api.api.v1 import auth

api_router = APIRouter(prefix=API_V1_PREFIX)
api_router.include_router(auth.router)
