"""User account: login identity and the owner of vault items."""

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vault_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from vault_api.models.item import VaultItem

EMAIL_MAX_LENGTH = 254  # longest address SMTP accepts (RFC 5321 path limit)
PASSWORD_HASH_MAX_LENGTH = 255


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered user. The password is stored only as a one-way hash."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)

    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(PASSWORD_HASH_MAX_LENGTH))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())

    items: Mapped[list["VaultItem"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )
