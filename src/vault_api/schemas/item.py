"""Request and response schemas for vault items, in plaintext.

Encryption happens between these schemas and the ORM model, never inside them.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator

NAME_MAX_LENGTH = 200
USERNAME_MAX_LENGTH = 320
SECRET_MAX_LENGTH = 1024
URL_MAX_LENGTH = 2048
NOTES_MAX_LENGTH = 10_000

# Optional text is either absent/null or non-empty; to clear a field, send null.
ItemName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH)
]
ItemUsername = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=USERNAME_MAX_LENGTH)
]
ItemSecret = Annotated[SecretStr, Field(min_length=1, max_length=SECRET_MAX_LENGTH)]
# Plain string, not HttpUrl: credentials also belong to app and non-HTTP URIs.
ItemUrl = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=URL_MAX_LENGTH)
]
# Not stripped, so the formatting of multi-line notes is kept as written.
ItemNotes = Annotated[str, StringConstraints(min_length=1, max_length=NOTES_MAX_LENGTH)]


class ItemCreate(BaseModel):
    """Request to store a new credential. Every field is kept out of `repr`."""

    model_config = ConfigDict(extra="forbid")

    name: ItemName = Field(repr=False)
    username: ItemUsername | None = Field(default=None, repr=False)
    password: ItemSecret
    url: ItemUrl | None = Field(default=None, repr=False)
    notes: ItemNotes | None = Field(default=None, repr=False)


class ItemUpdate(BaseModel):
    """Partial update. Only the fields present in the request are changed.

    `None` as a default means "not supplied". An explicit null clears the optional
    fields and is rejected for `name` and `password`, which every item must have.
    """

    model_config = ConfigDict(extra="forbid")

    name: ItemName | None = Field(default=None, repr=False)
    username: ItemUsername | None = Field(default=None, repr=False)
    password: ItemSecret | None = None
    url: ItemUrl | None = Field(default=None, repr=False)
    notes: ItemNotes | None = Field(default=None, repr=False)

    @field_validator("name", "password", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: Any) -> Any:
        """Refuse null for required fields; defaults skip validation, so omission is allowed."""
        if value is None:
            msg = "cannot be null; omit the field to keep its current value"
            raise ValueError(msg)
        return value


class ItemRead(BaseModel):
    """A decrypted credential returned to its owner.

    Decrypted fields are excluded from `repr`, so logging the model leaks nothing.
    """

    id: uuid.UUID
    name: str = Field(repr=False)
    username: str | None = Field(repr=False)
    password: str = Field(repr=False)
    url: str | None = Field(repr=False)
    notes: str | None = Field(repr=False)
    created_at: datetime
    updated_at: datetime
