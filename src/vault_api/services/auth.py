"""User registration and credential checks, independent of HTTP."""

from collections.abc import Callable

import anyio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vault_api.core.security import (
    DUMMY_PASSWORD,
    hash_password,
    verify_dummy_password,
    verify_password,
)
from vault_api.models import User
from vault_api.models.user import EMAIL_MAX_LENGTH
from vault_api.schemas.user import MASTER_PASSWORD_MAX_LENGTH, UserCreate

# Each Argon2 hash takes 64 MiB and noticeable CPU. A dedicated limiter caps the
# concurrent hashes, so a flood of logins queues instead of exhausting memory, and
# it does not consume the thread pool that other sync work shares.
MAX_CONCURRENT_HASHES = 4
_hashing_limiter = anyio.CapacityLimiter(MAX_CONCURRENT_HASHES)


class EmailAlreadyRegisteredError(Exception):
    """Registration used an email that already belongs to an account."""


async def _run_hashing[T](function: Callable[..., T], *args: str) -> T:
    return await anyio.to_thread.run_sync(function, *args, limiter=_hashing_limiter)


async def warm_up_password_hashing() -> None:
    """Compute the dummy hash at startup, so the first unknown-email login is not slower."""
    await _run_hashing(verify_dummy_password, DUMMY_PASSWORD)


def _cannot_be_valid(email: str, password: str) -> bool:
    """Credentials no account can have; refused before any query or hashing."""
    return (
        len(email) > EMAIL_MAX_LENGTH
        or "\x00" in email
        or len(password) > MASTER_PASSWORD_MAX_LENGTH
    )


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Find a user by email, ignoring letter case."""
    return await session.scalar(select(User).where(User.email == email.lower()))


async def register_user(session: AsyncSession, data: UserCreate) -> User:
    """Create an account with a hashed password."""
    if await get_user_by_email(session, data.email) is not None:
        raise EmailAlreadyRegisteredError(data.email)

    password_hash = await _run_hashing(hash_password, data.password.get_secret_value())
    user = User(email=data.email, password_hash=password_hash)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as error:  # a concurrent registration won the race
        await session.rollback()
        raise EmailAlreadyRegisteredError(data.email) from error
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    """Return the active user these credentials belong to, or None.

    Unknown emails, wrong passwords and inactive accounts each run one Argon2
    verification and give the same result, so the answer does not reveal which it was.
    Malformed credentials are refused without hashing, which reveals nothing about
    accounts.
    """
    if _cannot_be_valid(email, password):
        return None

    user = await get_user_by_email(session, email)
    if user is None:
        await _run_hashing(verify_dummy_password, password)
        return None

    check = await _run_hashing(verify_password, password, user.password_hash)
    if not check.is_valid or not user.is_active:
        return None
    if check.updated_hash is not None:
        user.password_hash = check.updated_hash
        await session.commit()
    return user
