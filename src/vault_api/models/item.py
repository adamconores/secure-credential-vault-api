"""Vault item: one stored credential, every field encrypted at rest."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from vault_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from vault_api.models.user import User

ENCRYPTED_COLUMNS = (
    "name_encrypted",
    "username_encrypted",
    "password_encrypted",
    "url_encrypted",
    "notes_encrypted",
)


class VaultItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A credential owned by one user.

    Every user-supplied field holds a Fernet token. The model never sees plaintext:
    `vault_api.core.security` encrypts before writing and decrypts after reading.
    Assigning a `str` to an encrypted column raises `TypeError`, so plaintext cannot
    slip in by mistake.
    """

    __tablename__ = "vault_items"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name_encrypted: Mapped[bytes]
    username_encrypted: Mapped[bytes | None]
    password_encrypted: Mapped[bytes]
    url_encrypted: Mapped[bytes | None]
    notes_encrypted: Mapped[bytes | None]

    owner: Mapped["User"] = relationship(back_populates="items")

    @validates(*ENCRYPTED_COLUMNS)
    def _require_ciphertext(self, column: str, value: bytes | None) -> bytes | None:
        if value is not None and not isinstance(value, bytes):
            msg = f"{column} takes Fernet ciphertext (bytes), got {type(value).__name__}"
            raise TypeError(msg)
        return value
