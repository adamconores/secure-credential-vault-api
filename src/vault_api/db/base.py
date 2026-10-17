"""Declarative base class, column types and mixins shared by every ORM model."""

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, Dialect, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

# Deterministic constraint names, so migrations can drop and alter constraints by name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Root of the ORM model hierarchy; its metadata describes the whole schema."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetime that is always stored and returned in UTC.

    SQLite drops the offset and returns naive values; they are UTC (`CURRENT_TIMESTAMP`),
    so UTC is attached on load. Naive values are refused on write.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            msg = f"naive datetime {value!r} has no timezone; pass an aware UTC value"
            raise ValueError(msg)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class UUIDPrimaryKeyMixin:
    """Random UUID4 primary key, so identifiers cannot be enumerated."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


def utc_now() -> datetime:
    """Current time in UTC with microseconds."""
    return datetime.now(UTC)


class TimestampMixin:
    """Creation and last-update times.

    ORM writes set them in Python with microsecond precision: SQLite's `CURRENT_TIMESTAMP`
    has one-second resolution, which would make "newest first" ambiguous for items
    created in the same second. The server defaults cover rows written without the ORM.
    """

    # Fetch any server-generated values in the INSERT/UPDATE itself (RETURNING), so an
    # async session never needs a lazy load to read them.
    __mapper_args__: ClassVar[dict[str, Any]] = {"eager_defaults": True}

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=func.now(), onupdate=utc_now
    )
