"""Vault item storage: the only place where item fields are encrypted and decrypted."""

import uuid

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vault_api.core.security import DecryptionError, FieldCipher
from vault_api.models import VaultItem
from vault_api.schemas.item import ItemCreate, ItemRead, ItemUpdate

ENCRYPTED_COLUMN_SUFFIX = "_encrypted"


class ItemNotFoundError(Exception):
    """No item with this id belongs to the requesting user."""


class StoredItemUnreadableError(Exception):
    """A stored item cannot be decrypted with the configured keys."""

    def __init__(self, item_id: uuid.UUID) -> None:
        super().__init__(f"vault item {item_id} cannot be decrypted with the configured keys")
        self.item_id = item_id


def _plaintext(value: str | SecretStr | None) -> str | None:
    return value.get_secret_value() if isinstance(value, SecretStr) else value


def _encrypt_optional(cipher: FieldCipher, value: str | None) -> bytes | None:
    return None if value is None else cipher.encrypt(value)


def _decrypt_optional(cipher: FieldCipher, token: bytes | None) -> str | None:
    return None if token is None else cipher.decrypt(token)


def to_item_read(item: VaultItem, cipher: FieldCipher) -> ItemRead:
    """Decrypt a stored item for its owner."""
    try:
        return ItemRead(
            id=item.id,
            name=cipher.decrypt(item.name_encrypted),
            username=_decrypt_optional(cipher, item.username_encrypted),
            password=cipher.decrypt(item.password_encrypted),
            url=_decrypt_optional(cipher, item.url_encrypted),
            notes=_decrypt_optional(cipher, item.notes_encrypted),
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
    except DecryptionError as error:
        raise StoredItemUnreadableError(item.id) from error


async def create_item(
    session: AsyncSession, owner_id: uuid.UUID, data: ItemCreate, cipher: FieldCipher
) -> VaultItem:
    """Encrypt and store a new item for its owner."""
    item = VaultItem(
        owner_id=owner_id,
        name_encrypted=cipher.encrypt(data.name),
        username_encrypted=_encrypt_optional(cipher, data.username),
        password_encrypted=cipher.encrypt(data.password.get_secret_value()),
        url_encrypted=_encrypt_optional(cipher, data.url),
        notes_encrypted=_encrypt_optional(cipher, data.notes),
    )
    session.add(item)
    await session.commit()
    return item


async def list_items(
    session: AsyncSession, owner_id: uuid.UUID, *, limit: int, offset: int
) -> list[VaultItem]:
    """Return one page of the owner's items, newest first."""
    statement = (
        select(VaultItem)
        .where(VaultItem.owner_id == owner_id)
        .order_by(VaultItem.created_at.desc(), VaultItem.id)
        .limit(limit)
        .offset(offset)
    )
    return list(await session.scalars(statement))


async def get_item(session: AsyncSession, owner_id: uuid.UUID, item_id: uuid.UUID) -> VaultItem:
    """Return the owner's item; another user's item is reported as missing."""
    item = await session.scalar(
        select(VaultItem).where(VaultItem.id == item_id, VaultItem.owner_id == owner_id)
    )
    if item is None:
        raise ItemNotFoundError(item_id)
    return item


async def update_item(
    session: AsyncSession,
    owner_id: uuid.UUID,
    item_id: uuid.UUID,
    data: ItemUpdate,
    cipher: FieldCipher,
) -> VaultItem:
    """Re-encrypt only the fields present in the update; null clears an optional field."""
    item = await get_item(session, owner_id, item_id)
    if not data.model_fields_set:
        return item
    for field in data.model_fields_set:
        plaintext = _plaintext(getattr(data, field))
        setattr(item, f"{field}{ENCRYPTED_COLUMN_SUFFIX}", _encrypt_optional(cipher, plaintext))
    await session.commit()
    return item


async def delete_item(session: AsyncSession, owner_id: uuid.UUID, item_id: uuid.UUID) -> None:
    """Delete the owner's item."""
    item = await get_item(session, owner_id, item_id)
    await session.delete(item)
    await session.commit()
