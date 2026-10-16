"""Request and response schemas for user accounts."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, SecretStr

from vault_api.models.user import EMAIL_MAX_LENGTH

MASTER_PASSWORD_MIN_LENGTH = 12
MASTER_PASSWORD_MAX_LENGTH = 128

# Stored lowercase, so lookups and the uniqueness constraint ignore letter case.
NormalizedEmail = Annotated[EmailStr, Field(max_length=EMAIL_MAX_LENGTH), AfterValidator(str.lower)]
MasterPassword = Annotated[
    SecretStr,
    Field(min_length=MASTER_PASSWORD_MIN_LENGTH, max_length=MASTER_PASSWORD_MAX_LENGTH),
]


class UserCreate(BaseModel):
    """Registration request."""

    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    password: MasterPassword


class UserRead(BaseModel):
    """Public view of a user. Never carries the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    is_active: bool
    created_at: datetime
