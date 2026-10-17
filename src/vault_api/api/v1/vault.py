"""CRUD endpoints for the current user's vault items."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from vault_api.api.dependencies import CipherDep, CurrentUserDep, SessionDep
from vault_api.api.paths import VAULT_ITEMS_PREFIX
from vault_api.schemas.item import ItemCreate, ItemRead, ItemUpdate
from vault_api.services import vault as vault_service

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

router = APIRouter(prefix=VAULT_ITEMS_PREFIX, tags=["vault"])


def item_not_found() -> HTTPException:
    """404 for both missing items and other users' items, so ids reveal nothing."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_item(
    data: ItemCreate, user: CurrentUserDep, session: SessionDep, cipher: CipherDep
) -> ItemRead:
    """Store a new credential."""
    item = await vault_service.create_item(session, user.id, data, cipher)
    return vault_service.to_item_read(item, cipher)


@router.get("")
async def list_items(
    user: CurrentUserDep,
    session: SessionDep,
    cipher: CipherDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ItemRead]:
    """List the current user's credentials, newest first."""
    items = await vault_service.list_items(session, user.id, limit=limit, offset=offset)
    return [vault_service.to_item_read(item, cipher) for item in items]


@router.get("/{item_id}")
async def read_item(
    item_id: uuid.UUID, user: CurrentUserDep, session: SessionDep, cipher: CipherDep
) -> ItemRead:
    """Return one credential."""
    try:
        item = await vault_service.get_item(session, user.id, item_id)
    except vault_service.ItemNotFoundError:
        raise item_not_found() from None
    return vault_service.to_item_read(item, cipher)


@router.patch("/{item_id}")
async def update_item(
    item_id: uuid.UUID,
    data: ItemUpdate,
    user: CurrentUserDep,
    session: SessionDep,
    cipher: CipherDep,
) -> ItemRead:
    """Change the fields present in the request; null clears an optional field."""
    try:
        item = await vault_service.update_item(session, user.id, item_id, data, cipher)
    except vault_service.ItemNotFoundError:
        raise item_not_found() from None
    return vault_service.to_item_read(item, cipher)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> None:
    """Delete one credential."""
    try:
        await vault_service.delete_item(session, user.id, item_id)
    except vault_service.ItemNotFoundError:
        raise item_not_found() from None
