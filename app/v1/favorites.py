"""Favorites: shares the signed-in user bookmarked.

Authenticated with a Firebase token like the dashboard routes, not an API key.
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import User, get_current_user
from app.public._share_auth import can_view_share
from core.supabase import get_admin_client
from models.share import FavoriteShare, FavoriteStatus

router = APIRouter(prefix="/favorites", tags=["Favorites"])

# Exactly the columns ShareMeta.from_row reads: no content columns, and password_hash only
# to derive has_password.
_FAVORITE_SHARE_COLUMNS = (
    "id, slug, user_id, filename, title, mime_type, language, file_size, view_count, "
    "created_at, expires_at, is_private, password_hash, burn_after_reading, burned, "
    "encrypted, group_id"
)


def _share_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Share not found")


async def _visible_share_id(share_id: str, user: User) -> str:
    """The normalized id of a share `user` may view; 404, the same for every cause, otherwise."""
    try:
        normalized = str(uuid.UUID(share_id))
    except ValueError:
        raise _share_not_found() from None
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("shares")
        .select("id, user_id, is_private")
        .eq("id", normalized)
        .execute()
    )
    rows = resp.data or []
    if not rows or not can_view_share(rows[0], user):
        raise _share_not_found()
    return normalized


@router.get("", response_model=list[FavoriteShare], summary="List favorites")
async def list_favorites(user: User = Depends(get_current_user)):
    """The caller's favorites, newest first. Shares that are no longer visible to them are omitted."""
    client = get_admin_client()
    favs = await asyncio.to_thread(
        lambda: client.table("favorites")
        .select("share_id, created_at")
        .eq("user_id", user.id)
        .order("created_at", desc=True)
        .execute()
    )
    fav_rows = favs.data or []
    if not fav_rows:
        return []

    share_ids = [row["share_id"] for row in fav_rows]
    shares = await asyncio.to_thread(
        lambda: client.table("shares")
        .select(_FAVORITE_SHARE_COLUMNS)
        .in_("id", share_ids)
        .execute()
    )
    by_id = {str(row["id"]): row for row in shares.data or []}

    items = []
    for fav in fav_rows:
        share = by_id.get(str(fav["share_id"]))
        if share is None or not can_view_share(share, user):
            continue
        items.append(
            FavoriteShare.from_favorite(
                share, fav["created_at"], is_owner=share.get("user_id") == user.id,
            )
        )
    return items


@router.get("/{share_id}", response_model=FavoriteStatus, summary="Is this share a favorite")
async def get_favorite(share_id: str, user: User = Depends(get_current_user)):
    try:
        normalized = str(uuid.UUID(share_id))
    except ValueError:
        return FavoriteStatus(favorited=False)
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("favorites")
        .select("share_id")
        .eq("user_id", user.id)
        .eq("share_id", normalized)
        .execute()
    )
    return FavoriteStatus(favorited=bool(resp.data))


@router.post("/{share_id}", response_model=FavoriteStatus, summary="Add a favorite")
async def add_favorite(share_id: str, user: User = Depends(get_current_user)):
    """Favorite a share the caller can view. Adding twice is not an error."""
    normalized = await _visible_share_id(share_id, user)
    client = get_admin_client()
    await asyncio.to_thread(
        lambda: client.table("favorites")
        .upsert(
            {"user_id": user.id, "share_id": normalized},
            on_conflict="user_id,share_id",
            ignore_duplicates=True,
        )
        .execute()
    )
    return FavoriteStatus(favorited=True)


@router.delete("/{share_id}", response_model=FavoriteStatus, summary="Remove a favorite")
async def remove_favorite(share_id: str, user: User = Depends(get_current_user)):
    """Unfavorite a share. Removing one that is not a favorite is not an error."""
    try:
        normalized = str(uuid.UUID(share_id))
    except ValueError:
        return FavoriteStatus(favorited=False)
    client = get_admin_client()
    await asyncio.to_thread(
        lambda: client.table("favorites")
        .delete()
        .eq("user_id", user.id)
        .eq("share_id", normalized)
        .execute()
    )
    return FavoriteStatus(favorited=False)
