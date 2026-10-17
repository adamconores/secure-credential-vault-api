"""Registration, login and current-user endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from vault_api.api.dependencies import (
    BEARER_CHALLENGE,
    CurrentUserDep,
    SessionDep,
    SettingsDep,
)
from vault_api.api.paths import AUTH_PREFIX, LOGIN_PATH
from vault_api.core.security import create_access_token
from vault_api.schemas.token import AccessToken
from vault_api.schemas.user import UserCreate, UserRead
from vault_api.services.auth import EmailAlreadyRegisteredError, authenticate, register_user

SECONDS_PER_MINUTE = 60

router = APIRouter(prefix=AUTH_PREFIX, tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: UserCreate, session: SessionDep) -> UserRead:
    """Create an account."""
    try:
        user = await register_user(session, data)
    except EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email is already registered"
        ) from None
    return UserRead.model_validate(user)


@router.post(LOGIN_PATH)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
    settings: SettingsDep,
) -> AccessToken:
    """Exchange email (as `username`) and password for a bearer token."""
    user = await authenticate(session, form.username, form.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers=BEARER_CHALLENGE,
        )
    return AccessToken(
        access_token=create_access_token(user.id, settings),
        expires_in=settings.access_token_ttl_minutes * SECONDS_PER_MINUTE,
    )


@router.get("/me")
async def read_current_user(user: CurrentUserDep) -> UserRead:
    """Return the account the bearer token belongs to."""
    return UserRead.model_validate(user)
