"""Favorites: shares the signed-in user bookmarked.

Authenticated with a Firebase token like the dashboard routes, not an API key.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

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
    "one_time_download, encrypted, group_id"
)


def _share_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Share not found")


def _has_expired(share: dict) -> bool:
    expires_at = share.get("expires_at")
    if not expires_at:
        return False
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    return expires_at <= datetime.now(timezone.utc)


def _is_favorable(share: dict, user: User) -> bool:
    """Whether `user` still sees `share` as a favorite: visible to them and, unless they own it, not burned or expired."""
    if not can_view_share(share, user):
        return False
    if share.get("user_id") == user.id:
        return True
    return not share.get("burned") and not _has_expired(share)


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
    """The caller's favorites, newest first. Shares that are no longer visible to them, or that
    someone else's burn or expiry ended, are omitted."""
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
        if share is None or not _is_favorable(share, user):
            continue
        items.append(
            FavoriteShare.from_favorite(
                share, fav["created_at"], is_owner=share.get("user_id") == user.id,
            )
        )
    return items


@router.get("/{share_id}", response_model=FavoriteStatus, summary="Is this share a favorite")
async def get_favorite(share_id: str, user: User = Depends(get_current_user)):
    """Whether the share is a favorite; false once it is no longer visible and live to the caller."""
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
    if not resp.data:
        return FavoriteStatus(favorited=False)
    shares = await asyncio.to_thread(
        lambda: client.table("shares")
        .select("id, user_id, is_private, burned, expires_at")
        .eq("id", normalized)
        .execute()
    )
    share = (shares.data or [None])[0]
    return FavoriteStatus(favorited=share is not None and _is_favorable(share, user))


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
