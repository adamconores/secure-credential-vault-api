"""Response schema for issued access tokens."""

from typing import Literal

from pydantic import BaseModel, Field


class AccessToken(BaseModel):
    """OAuth2 bearer token response (RFC 6749, section 5.1)."""

    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  (OAuth2 token type, not a secret)
    expires_in: int  # seconds
