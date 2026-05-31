"""Star/like endpoints for shares."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import User, get_current_user, get_optional_user
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class StarStatus(BaseModel):
    """Star status for a share."""
    starred: bool
    count: int


class StarAction(BaseModel):
    """Response after starring/unstarring."""
    starred: bool
    count: int


# ---------------------------------------------------------------------------
# GET /shares/{slug}/star — check star status
# ---------------------------------------------------------------------------

@router.get(
    "/shares/{slug}/star",
    tags=["Stars"],
    summary="Get star status for a share",
)
async def get_star_status(
    slug: str,
    user: User | None = Depends(get_optional_user),
):
    """Get star count and whether the current user has starred."""
    client = get_admin_client()

    # Get share id from slug
    share_resp = await asyncio.to_thread(
        lambda: client.table("shares").select("id").eq("slug", slug).execute()
    )
    if not share_resp.data:
        raise HTTPException(status_code=404, detail="Share not found")
    share_id = share_resp.data[0]["id"]

    # Get star count
    count_resp = await asyncio.to_thread(
        lambda: client.rpc("get_star_count", {"p_share_id": share_id}).execute()
    )
    count = count_resp.data or 0

    # Check if current user has starred (if authenticated)
    starred = False
    if user:
        try:
            starred_resp = await asyncio.to_thread(
                lambda: client.rpc(
                    "has_user_starred",
                    {"p_share_id": share_id, "p_user_id": user.id},
                ).execute()
            )
            starred = bool(starred_resp.data)
        except Exception:
            pass

    return StarStatus(starred=starred, count=count)


# ---------------------------------------------------------------------------
# POST /shares/{slug}/star — star a share
# ---------------------------------------------------------------------------

@router.post(
    "/shares/{slug}/star",
    tags=["Stars"],
    summary="Star a share",
)
async def star_share(
    slug: str,
    user: User = Depends(get_current_user),
):
    """Star a share. Requires authentication."""
    client = get_admin_client()

    # Get share id
    share_resp = await asyncio.to_thread(
        lambda: client.table("shares").select("id").eq("slug", slug).execute()
    )
    if not share_resp.data:
        raise HTTPException(status_code=404, detail="Share not found")
    share_id = share_resp.data[0]["id"]

    # Insert star (ignore if already exists)
    try:
        await asyncio.to_thread(
            lambda: client.table("share_stars")
            .upsert(
                {"share_id": share_id, "user_id": user.id},
                on_conflict="share_id,user_id",
            )
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to star share %s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to star") from exc

    # Get updated count
    count_resp = await asyncio.to_thread(
        lambda: client.rpc("get_star_count", {"p_share_id": share_id}).execute()
    )
    count = count_resp.data or 0

    return StarAction(starred=True, count=count)


# ---------------------------------------------------------------------------
# DELETE /shares/{slug}/star — unstar a share
# ---------------------------------------------------------------------------

@router.delete(
    "/shares/{slug}/star",
    tags=["Stars"],
    summary="Unstar a share",
)
async def unstar_share(
    slug: str,
    user: User = Depends(get_current_user),
):
    """Remove star from a share. Requires authentication."""
    client = get_admin_client()

    # Get share id
    share_resp = await asyncio.to_thread(
        lambda: client.table("shares").select("id").eq("slug", slug).execute()
    )
    if not share_resp.data:
        raise HTTPException(status_code=404, detail="Share not found")
    share_id = share_resp.data[0]["id"]

    # Delete star
    try:
        await asyncio.to_thread(
            lambda: client.table("share_stars")
            .delete()
            .eq("share_id", share_id)
            .eq("user_id", user.id)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to unstar share %s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to unstar") from exc

    # Get updated count
    count_resp = await asyncio.to_thread(
        lambda: client.rpc("get_star_count", {"p_share_id": share_id}).execute()
    )
    count = count_resp.data or 0

    return StarAction(starred=False, count=count)
