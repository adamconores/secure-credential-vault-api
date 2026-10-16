import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from vault_api.models import User
from vault_api.schemas.item import NAME_MAX_LENGTH, ItemCreate, ItemRead, ItemUpdate
from vault_api.schemas.user import (
    MASTER_PASSWORD_MAX_LENGTH,
    MASTER_PASSWORD_MIN_LENGTH,
    UserCreate,
    UserRead,
)

VALID_MASTER_PASSWORD = "correct horse battery staple"


def test_user_create_normalizes_email_to_lowercase() -> None:
    user = UserCreate(email="Owner@Example.COM", password=VALID_MASTER_PASSWORD)

    assert user.email == "owner@example.com"


def test_user_create_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(email="not-an-email", password=VALID_MASTER_PASSWORD)

    assert exc_info.value.errors()[0]["loc"] == ("email",)


@pytest.mark.parametrize(
    ("password", "error_type"),
    [
        ("x" * (MASTER_PASSWORD_MIN_LENGTH - 1), "too_short"),
        ("x" * (MASTER_PASSWORD_MAX_LENGTH + 1), "too_long"),
    ],
    ids=["too-short", "too-long"],
)
def test_user_create_rejects_master_password_outside_length_bounds(
    password: str, error_type: str
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(email="owner@example.com", password=password)

    error = exc_info.value.errors()[0]
    assert (error["loc"], error["type"]) == (("password",), error_type)


def test_user_create_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="is_active"):
        UserCreate.model_validate(
            {"email": "owner@example.com", "password": VALID_MASTER_PASSWORD, "is_active": False}
        )


def test_passwords_never_appear_in_repr() -> None:
    user = UserCreate(email="owner@example.com", password=VALID_MASTER_PASSWORD)
    item = ItemCreate(name="Mail", password="item-secret")

    assert VALID_MASTER_PASSWORD not in repr(user)
    assert "item-secret" not in repr(item)


def test_user_read_omits_password_hash() -> None:
    user = User(
        id=uuid.uuid4(),
        email="owner@example.com",
        password_hash="$argon2id$secret-hash",
        is_active=True,
        created_at=datetime.now(UTC),
    )

    dumped = UserRead.model_validate(user).model_dump()

    assert "password_hash" not in dumped
    assert "$argon2id$secret-hash" not in str(dumped)


def test_item_create_strips_name_and_rejects_blank_name() -> None:
    assert ItemCreate(name="  Mail  ", password="s").name == "Mail"
    with pytest.raises(ValidationError, match="name"):
        ItemCreate(name="   ", password="s")


def test_item_create_rejects_overlong_name() -> None:
    with pytest.raises(ValidationError, match="name"):
        ItemCreate(name="x" * (NAME_MAX_LENGTH + 1), password="s")


def test_item_update_tracks_only_supplied_fields() -> None:
    update = ItemUpdate(notes=None, url="https://example.com")

    assert update.model_fields_set == {"notes", "url"}


@pytest.mark.parametrize("field", ["name", "password"])
def test_item_update_rejects_null_for_required_fields(field: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ItemUpdate.model_validate({field: None})

    assert exc_info.value.errors()[0]["loc"] == (field,)


def test_item_read_keeps_decrypted_values_out_of_repr() -> None:
    item = ItemRead(
        id=uuid.uuid4(),
        name="Bank",
        username="alice",
        password="item-secret",
        url="https://bank.example",
        notes="pin 1234",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    for secret in ("Bank", "alice", "item-secret", "bank.example", "pin 1234"):
        assert secret not in repr(item)
    assert item.model_dump()["password"] == "item-secret"


def test_item_create_rejects_blank_optional_text() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ItemCreate(name="Mail", password="s", username="   ")

    assert exc_info.value.errors()[0]["loc"] == ("username",)
