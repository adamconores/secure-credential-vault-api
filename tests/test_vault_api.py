import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx2
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vault_api.api.middleware import MAX_REQUEST_BODY_BYTES
from vault_api.api.v1.vault import MAX_PAGE_SIZE
from vault_api.core.config import get_settings
from vault_api.core.security import get_field_cipher
from vault_api.models import VaultItem
from vault_api.schemas.item import (
    NAME_MAX_LENGTH,
    NOTES_MAX_LENGTH,
    SECRET_MAX_LENGTH,
    URL_MAX_LENGTH,
    USERNAME_MAX_LENGTH,
)

pytestmark = pytest.mark.anyio

ITEMS_URL = "/api/v1/vault/items"
PASSWORD = "correct horse battery staple"
FULL_ITEM = {
    "name": "Bank",
    "username": "alice",
    "password": "s3cr3t-item-password",
    "url": "https://bank.example",
    "notes": "PIN 4321",
}


async def auth_headers(client: httpx2.AsyncClient, email: str) -> dict[str, str]:
    await client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    response = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def alice(client: httpx2.AsyncClient) -> dict[str, str]:
    return await auth_headers(client, "alice@example.com")


@pytest.fixture
async def bob(client: httpx2.AsyncClient) -> dict[str, str]:
    return await auth_headers(client, "bob@example.com")


async def create(
    client: httpx2.AsyncClient, headers: dict[str, str], **fields: str
) -> dict[str, object]:
    response = await client.post(ITEMS_URL, json=fields or FULL_ITEM, headers=headers)
    assert response.status_code == 201
    body: dict[str, object] = response.json()
    return body


async def test_item_lifecycle(client: httpx2.AsyncClient, alice: dict[str, str]) -> None:
    created = await create(client, alice)
    item_url = f"{ITEMS_URL}/{created['id']}"
    assert {key: created[key] for key in FULL_ITEM} == FULL_ITEM

    assert (await client.get(item_url, headers=alice)).json() == created
    assert (await client.get(ITEMS_URL, headers=alice)).json() == [created]

    updated = await client.patch(item_url, json={"notes": "PIN changed"}, headers=alice)
    assert updated.status_code == 200
    assert updated.json()["notes"] == "PIN changed"
    assert updated.json()["password"] == FULL_ITEM["password"]

    assert (await client.delete(item_url, headers=alice)).status_code == 204
    assert (await client.get(item_url, headers=alice)).status_code == 404


async def test_items_are_encrypted_at_rest(
    client: httpx2.AsyncClient, alice: dict[str, str], db_session: AsyncSession
) -> None:
    await create(client, alice)

    stored = await db_session.scalar(select(VaultItem))

    assert stored is not None
    cipher = get_field_cipher()
    columns = {
        "name": stored.name_encrypted,
        "username": stored.username_encrypted,
        "password": stored.password_encrypted,
        "url": stored.url_encrypted,
        "notes": stored.notes_encrypted,
    }
    for field, token in columns.items():
        assert token is not None
        assert FULL_ITEM[field].encode() not in token
        assert cipher.decrypt(token) == FULL_ITEM[field]


async def test_other_users_items_are_invisible(
    client: httpx2.AsyncClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    created = await create(client, alice)
    item_url = f"{ITEMS_URL}/{created['id']}"

    assert (await client.get(item_url, headers=bob)).status_code == 404
    assert (await client.patch(item_url, json={"notes": "x"}, headers=bob)).status_code == 404
    assert (await client.delete(item_url, headers=bob)).status_code == 404
    assert (await client.get(ITEMS_URL, headers=bob)).json() == []
    assert (await client.get(item_url, headers=alice)).json() == created


async def test_missing_and_foreign_items_get_identical_answers(
    client: httpx2.AsyncClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    created = await create(client, alice)

    foreign = await client.get(f"{ITEMS_URL}/{created['id']}", headers=bob)
    missing = await client.get(f"{ITEMS_URL}/{uuid.uuid4()}", headers=bob)

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


async def test_patch_null_clears_optional_fields_only(
    client: httpx2.AsyncClient, alice: dict[str, str]
) -> None:
    created = await create(client, alice)
    item_url = f"{ITEMS_URL}/{created['id']}"

    cleared = await client.patch(item_url, json={"username": None, "url": None}, headers=alice)
    assert cleared.status_code == 200
    assert cleared.json()["username"] is None
    assert cleared.json()["url"] is None
    assert cleared.json()["notes"] == FULL_ITEM["notes"]

    for field in ("name", "password"):
        response = await client.patch(item_url, json={field: None}, headers=alice)
        assert response.status_code == 422


async def test_empty_patch_changes_nothing(
    client: httpx2.AsyncClient, alice: dict[str, str]
) -> None:
    created = await create(client, alice)

    response = await client.patch(f"{ITEMS_URL}/{created['id']}", json={}, headers=alice)

    assert response.json() == created


async def test_patch_advances_updated_at(
    client: httpx2.AsyncClient, alice: dict[str, str], db_session: AsyncSession
) -> None:
    created = await create(client, alice)
    stored = await db_session.scalar(select(VaultItem))
    assert stored is not None
    stored.updated_at = datetime(2000, 1, 1, tzinfo=UTC)
    await db_session.commit()

    updated = await client.patch(
        f"{ITEMS_URL}/{created['id']}", json={"name": "Bank 2"}, headers=alice
    )

    assert datetime.fromisoformat(updated.json()["updated_at"]).year > 2000
    assert updated.json()["created_at"] == created["created_at"]


async def test_list_pages_newest_first(client: httpx2.AsyncClient, alice: dict[str, str]) -> None:
    ids = [
        str((await create(client, alice, name=f"item {n}", password="p"))["id"]) for n in range(3)
    ]

    first_page = (await client.get(ITEMS_URL, params={"limit": 2}, headers=alice)).json()
    second_page = (
        await client.get(ITEMS_URL, params={"limit": 2, "offset": 2}, headers=alice)
    ).json()

    # Created within the same second: the order must still be exact.
    assert [item["id"] for item in first_page + second_page] == list(reversed(ids))
    assert len(first_page) == 2


@pytest.mark.parametrize(
    "params",
    [{"limit": MAX_PAGE_SIZE + 1}, {"limit": 0}, {"offset": -1}],
    ids=["limit-too-high", "limit-zero", "negative-offset"],
)
async def test_invalid_paging_is_rejected(
    client: httpx2.AsyncClient, alice: dict[str, str], params: dict[str, int]
) -> None:
    assert (await client.get(ITEMS_URL, params=params, headers=alice)).status_code == 422


async def test_malformed_item_id_is_rejected(
    client: httpx2.AsyncClient, alice: dict[str, str]
) -> None:
    assert (await client.get(f"{ITEMS_URL}/not-a-uuid", headers=alice)).status_code == 422


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", ""), ("POST", ""), ("GET", "/{id}"), ("PATCH", "/{id}"), ("DELETE", "/{id}")],
)
async def test_vault_requires_authentication(
    client: httpx2.AsyncClient, method: str, path: str
) -> None:
    url = ITEMS_URL + path.format(id=uuid.uuid4())

    response = await client.request(method, url, json=FULL_ITEM if method == "POST" else None)

    assert response.status_code == 401


async def test_api_responses_are_not_cacheable(
    client: httpx2.AsyncClient, alice: dict[str, str]
) -> None:
    created = await create(client, alice)
    item_url = f"{ITEMS_URL}/{created['id']}"

    responses = [
        await client.get(ITEMS_URL, headers=alice),
        await client.get(item_url, headers=alice),
        await client.post(ITEMS_URL, json=FULL_ITEM, headers=alice),
        await client.patch(item_url, json={"name": None}, headers=alice),
        await client.get(f"{ITEMS_URL}/{uuid.uuid4()}", headers=alice),
        await client.get(ITEMS_URL),
        await client.post(
            "/api/v1/auth/login", data={"username": "alice@example.com", "password": PASSWORD}
        ),
    ]

    assert [response.headers.get("cache-control") for response in responses] == (
        ["no-store"] * len(responses)
    )


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "", {**FULL_ITEM, "password": "LEAKED-" + "x" * SECRET_MAX_LENGTH}),
        ("POST", "", {**FULL_ITEM, "owner_id": "LEAKED-extra-field"}),
        ("PATCH", "/{id}", {"url": "LEAKED-" + "x" * URL_MAX_LENGTH}),
    ],
    ids=["overlong-password", "extra-field", "overlong-url-patch"],
)
async def test_validation_errors_never_echo_submitted_values(
    client: httpx2.AsyncClient,
    alice: dict[str, str],
    method: str,
    path: str,
    body: dict[str, str],
) -> None:
    created = await create(client, alice)
    url = ITEMS_URL + path.format(id=created["id"])

    response = await client.request(method, url, json=body, headers=alice)

    assert response.status_code == 422
    assert "LEAKED" not in response.text
    for error in response.json()["detail"]:
        assert set(error) == {"loc", "msg", "type"}


async def test_list_fails_loudly_when_an_item_is_unreadable(
    client: httpx2.AsyncClient, alice: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await create(client, alice)
    monkeypatch.setenv("VAULT_FERNET_KEYS", Fernet.generate_key().decode())
    get_settings.cache_clear()
    get_field_cipher.cache_clear()

    response = await client.get(ITEMS_URL, headers=alice)

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


async def test_item_under_retired_key_gives_generic_error_without_leaking(
    client: httpx2.AsyncClient,
    alice: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    created = await create(client, alice)
    monkeypatch.setenv("VAULT_FERNET_KEYS", Fernet.generate_key().decode())
    get_settings.cache_clear()
    get_field_cipher.cache_clear()

    with caplog.at_level(logging.ERROR):
        response = await client.get(f"{ITEMS_URL}/{created['id']}", headers=alice)

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert str(created["id"]) in caplog.text
    for secret in FULL_ITEM.values():
        assert secret not in caplog.text
        assert secret not in response.text


async def test_oversized_body_with_content_length_is_rejected(
    client: httpx2.AsyncClient, alice: dict[str, str]
) -> None:
    oversized = b"x" * (MAX_REQUEST_BODY_BYTES + 1)

    response = await client.post(
        ITEMS_URL, content=oversized, headers={**alice, "Content-Type": "application/json"}
    )

    assert response.status_code == 413


async def test_oversized_chunked_body_is_rejected(
    client: httpx2.AsyncClient, alice: dict[str, str]
) -> None:
    chunk = b"x" * 1024
    chunk_count = MAX_REQUEST_BODY_BYTES // len(chunk) + 1

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(chunk_count):
            yield chunk

    response = await client.post(
        ITEMS_URL, content=chunks(), headers={**alice, "Content-Type": "application/json"}
    )

    assert response.status_code == 413


@pytest.mark.parametrize("ensure_ascii", [False, True], ids=["utf-8", "ascii-escaped"])
async def test_largest_valid_item_fits_under_the_body_limit(
    client: httpx2.AsyncClient, alice: dict[str, str], ensure_ascii: bool
) -> None:
    # An astral character is the worst case: 4 bytes in UTF-8, 12 bytes as a
    # \\uXXXX surrogate pair when the client escapes non-ASCII (json.dumps default).
    widest_character = "\U0001f511"
    largest = {
        "name": widest_character * NAME_MAX_LENGTH,
        "username": widest_character * USERNAME_MAX_LENGTH,
        "password": widest_character * SECRET_MAX_LENGTH,
        "url": widest_character * URL_MAX_LENGTH,
        "notes": widest_character * NOTES_MAX_LENGTH,
    }
    body = json.dumps(largest, ensure_ascii=ensure_ascii).encode()

    response = await client.post(
        ITEMS_URL, content=body, headers={**alice, "Content-Type": "application/json"}
    )

    assert response.status_code == 201
