import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vault_api.models import User, VaultItem

pytestmark = pytest.mark.anyio

PLACEHOLDER_HASH = "$argon2id$placeholder"
PLACEHOLDER_TOKEN = b"gAAAAA-placeholder-fernet-token"


def make_user(email: str = "owner@example.com") -> User:
    return User(email=email, password_hash=PLACEHOLDER_HASH)


def make_item(owner_id: uuid.UUID) -> VaultItem:
    return VaultItem(
        owner_id=owner_id,
        name_encrypted=PLACEHOLDER_TOKEN,
        password_encrypted=PLACEHOLDER_TOKEN,
    )


async def test_user_and_item_round_trip(db_session: AsyncSession) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.flush()
    db_session.add(make_item(user.id))
    await db_session.commit()

    stored = await db_session.scalar(select(VaultItem).where(VaultItem.owner_id == user.id))

    assert stored is not None
    assert stored.name_encrypted == PLACEHOLDER_TOKEN
    assert stored.username_encrypted is None
    assert stored.created_at is not None
    assert user.is_active


async def test_duplicate_email_is_rejected(db_session: AsyncSession) -> None:
    db_session.add(make_user())
    await db_session.commit()

    db_session.add(make_user())
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_uppercase_email_is_rejected(db_session: AsyncSession) -> None:
    db_session.add(make_user("Owner@Example.com"))

    with pytest.raises(IntegrityError, match="email_lowercase"):
        await db_session.commit()


async def test_item_without_existing_owner_is_rejected(db_session: AsyncSession) -> None:
    db_session.add(make_item(uuid.uuid4()))

    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        await db_session.commit()


async def test_deleting_user_deletes_their_items(db_session: AsyncSession) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.flush()
    db_session.add_all([make_item(user.id), make_item(user.id)])
    await db_session.commit()

    await db_session.delete(user)
    await db_session.commit()

    assert await db_session.scalar(select(func.count()).select_from(VaultItem)) == 0


async def test_update_refreshes_updated_at_without_lazy_load(db_session: AsyncSession) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.flush()
    long_ago = datetime(2000, 1, 1, tzinfo=UTC)
    item = make_item(user.id)
    item.updated_at = long_ago
    db_session.add(item)
    await db_session.commit()

    item.name_encrypted = b"gAAAAA-updated-token"
    await db_session.commit()

    assert item.updated_at > long_ago


async def test_timestamps_are_timezone_aware_utc(db_session: AsyncSession) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.commit()

    assert user.created_at.utcoffset() == timedelta(0)


async def test_is_active_defaults_to_true_in_database(db_session: AsyncSession) -> None:
    await db_session.execute(
        insert(User).values(
            id=uuid.uuid4(), email="raw@example.com", password_hash=PLACEHOLDER_HASH
        )
    )

    assert await db_session.scalar(select(User.is_active)) is True
