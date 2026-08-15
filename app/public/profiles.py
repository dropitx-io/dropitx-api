"""Public user profile endpoints."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class PublicProfile(BaseModel):
    """Public user profile."""
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    share_count: int = 0
    total_views: int = 0
    total_stars: int = 0


class ProfileShare(BaseModel):
    """A share listed on a user's public profile."""
    slug: str
    filename: str
    title: str | None = None
    tags: list[str] = []
    view_count: int = 0
    star_count: int = 0
    created_at: str


class ProfileSharesResponse(BaseModel):
    """Paginated shares for a user profile."""
    shares: list[ProfileShare]
    page: int
    limit: int
    has_more: bool


# ---------------------------------------------------------------------------
# GET /u/{username} — public profile
# ---------------------------------------------------------------------------

@router.get(
    "/u/{username}",
    tags=["Profiles"],
    summary="Get public user profile",
)
async def get_public_profile(username: str):
    """Get a user's public profile by username."""
    client = get_admin_client()

    # Get profile
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("user_profiles")
            .select("id, username, display_name, avatar_url, bio, is_public")
            .eq("username", username)
            .eq("is_public", True)
            .execute()
        )
    except Exception as exc:
        logger.error("Profile lookup failed for %s: %s", username, exc)
        raise HTTPException(status_code=500, detail="Profile lookup failed") from exc

    if not resp.data:
        raise HTTPException(status_code=404, detail="Profile not found")

    profile = resp.data[0]
    user_id = profile["id"]

    # Get share stats
    try:
        shares_resp = await asyncio.to_thread(
            lambda: client.table("public_shares")
            .select("id, view_count, star_count")
            .eq("user_id", user_id)
            .execute()
        )
        shares = shares_resp.data or []
    except Exception:
        shares = []

    share_count = len(shares)
    total_views = sum(s.get("view_count", 0) for s in shares)
    total_stars = sum(s.get("star_count", 0) for s in shares)

    return PublicProfile(
        username=profile["username"],
        display_name=profile.get("display_name"),
        avatar_url=profile.get("avatar_url"),
        bio=profile.get("bio"),
        share_count=share_count,
        total_views=total_views,
        total_stars=total_stars,
    )


# ---------------------------------------------------------------------------
# GET /u/{username}/shares — user's public shares
# ---------------------------------------------------------------------------

@router.get(
    "/u/{username}/shares",
    tags=["Profiles"],
    summary="List user's public shares",
)
async def list_user_shares(
    username: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    sort: str = Query(default="recent", description="Sort: recent, views, stars"),
):
    """Get a user's public shares."""
    client = get_admin_client()

    # Look up user_id from username
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("user_profiles")
            .select("id, is_public")
            .eq("username", username)
            .execute()
        )
    except Exception as exc:
        logger.error("Profile lookup failed for %s: %s", username, exc)
        raise HTTPException(status_code=500, detail="Profile lookup failed") from exc

    if not resp.data:
        raise HTTPException(status_code=404, detail="User not found")

    profile = resp.data[0]
    if not profile.get("is_public"):
        raise HTTPException(status_code=404, detail="Profile is not public")

    user_id = profile["id"]
    offset = (page - 1) * limit

    order_col = {
        "recent": "created_at",
        "views": "view_count",
        "stars": "star_count",
    }.get(sort, "created_at")

    try:
        shares_resp = await asyncio.to_thread(
            lambda: client.table("public_shares")
            .select("*", count="exact")
            .eq("user_id", user_id)
            .order(order_col, desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to fetch shares for %s: %s", username, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch shares") from exc

    rows = shares_resp.data or []
    total = shares_resp.count or 0

    # Normalize tags
    for row in rows:
        if isinstance(row.get("tags"), str):
            raw = row["tags"].strip("{}")
            row["tags"] = [t.strip().strip('"') for t in raw.split(",") if t.strip()] if raw else []
        elif not isinstance(row.get("tags"), list):
            row["tags"] = []

    shares = [ProfileShare(**row) for row in rows]

    return ProfileSharesResponse(
        shares=shares,
        page=page,
        limit=limit,
        has_more=(offset + limit) < total,
    )
