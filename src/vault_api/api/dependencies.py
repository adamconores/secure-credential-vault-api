"""Reusable FastAPI dependencies for the API routers."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from vault_api.api.paths import TOKEN_URL
from vault_api.core.config import Settings, get_settings
from vault_api.core.security import (
    FieldCipher,
    InvalidAccessTokenError,
    decode_access_token,
    get_field_cipher,
)
from vault_api.db.session import get_session
from vault_api.models import User

BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
CipherDep = Annotated[FieldCipher, Depends(get_field_cipher)]

# Missing or non-Bearer Authorization headers are answered with 401 by the scheme itself.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=TOKEN_URL)


def credentials_error() -> HTTPException:
    """The single 401 answer for every authentication failure."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers=BEARER_CHALLENGE,
    )


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep, settings: SettingsDep
) -> User:
    """Resolve the bearer token to an active user, or answer 401."""
    try:
        user_id = decode_access_token(token, settings)
    except InvalidAccessTokenError:
        raise credentials_error() from None

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error()
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
