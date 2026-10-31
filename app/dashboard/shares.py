"""The signed-in user's own shares."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query

from app.dependencies import User, get_current_user
from core.supabase import get_admin_client
from models.share import ShareListResponse, ShareMeta

router = APIRouter()

# Exactly the columns ShareMeta.from_row reads: no content columns, and password_hash only
# to derive has_password.
_OWN_SHARE_COLUMNS = (
    "id, slug, user_id, filename, title, mime_type, language, file_size, view_count, "
    "created_at, expires_at, is_private, password_hash, burn_after_reading, burned, "
    "encrypted, group_id"
)


@router.get("/shares", response_model=ShareListResponse, tags=["Shares"])
async def list_my_shares(
    user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """The caller's own shares, newest first. Owner view: private and expired shares included."""
    client = get_admin_client()
    start = (page - 1) * limit
    resp = await asyncio.to_thread(
        lambda: client.table("shares")
        .select(_OWN_SHARE_COLUMNS, count="exact")
        .eq("user_id", user.id)
        .order("created_at", desc=True)
        .range(start, start + limit - 1)
        .execute()
    )
    rows = resp.data or []
    return ShareListResponse(
        items=[ShareMeta.from_row(row, is_owner=True) for row in rows],
        total=resp.count if resp.count is not None else len(rows),
        page=page,
        limit=limit,
    )
