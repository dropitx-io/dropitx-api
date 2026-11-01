"""Public user profile endpoints."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timezone

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
# Helpers
# ---------------------------------------------------------------------------

# Listing columns only: never content, password hash, delete token or storage path.
_OPEN_SHARE_COLUMNS = (
    "id, slug, filename, title, tags, view_count, created_at, expires_at, "
    "burn_after_reading, one_time_download"
)

_SORT_KEYS = {
    "recent": lambda s: s["created_at"],
    "views": lambda s: (s.get("view_count") or 0, s["created_at"]),
    "stars": lambda s: (s["star_count"], s["created_at"]),
}


async def _public_profile(username: str) -> dict:
    """The profile row behind /u/{username}; 404 unless it exists and its owner made it public."""
    client = get_admin_client()
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("user_profiles")
            .select("user_id, username, display_name, avatar_url, bio, is_public")
            .eq("username", username.lower())
            .eq("is_public", True)
            .execute()
        )
    except Exception as exc:
        logger.error("Profile lookup failed for %s: %s", username, exc)
        raise HTTPException(status_code=500, detail="Profile lookup failed") from exc
    if not resp.data:
        raise HTTPException(status_code=404, detail="Profile not found")
    return resp.data[0]


def _is_expired(expires_at) -> bool:
    if not expires_at:
        return False
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    return datetime.now(timezone.utc) > expires_at


async def _open_shares(user_id: str) -> list[dict]:
    """The user's shares anyone may open from their profile, each with its star_count.

    Left out: private, password-protected, burned and expired shares, and the
    ephemeral burn-after-reading and one-time-download shares that one visit consumes.
    """
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("shares")
        .select(_OPEN_SHARE_COLUMNS)
        .eq("user_id", user_id)
        .eq("is_private", False)
        .eq("burned", False)
        .is_("password_hash", None)
        .execute()
    )
    shares = [
        row for row in resp.data or []
        if not (_is_expired(row.get("expires_at")) or row.get("burn_after_reading") or row.get("one_time_download"))
    ]
    ids = [row["id"] for row in shares]
    stars: Counter = Counter()
    if ids:
        star_rows = await asyncio.to_thread(
            lambda: client.table("share_stars").select("share_id").in_("share_id", ids).execute()
        )
        stars = Counter(row["share_id"] for row in star_rows.data or [])
    for row in shares:
        row["star_count"] = stars[row["id"]]
    return shares


# ---------------------------------------------------------------------------
# GET /u/{username} — public profile
# ---------------------------------------------------------------------------

@router.get(
    "/u/{username}",
    response_model=PublicProfile,
    tags=["Profiles"],
    summary="Get public user profile",
)
async def get_public_profile(username: str):
    """A user's public profile: handle, display name, avatar, bio and open-share stats. Never the email."""
    profile = await _public_profile(username)
    try:
        shares = await _open_shares(profile["user_id"])
    except Exception:
        logger.warning("Share stats failed for %s", username, exc_info=True)
        shares = []

    return PublicProfile(
        username=profile["username"],
        display_name=profile.get("display_name"),
        avatar_url=profile.get("avatar_url"),
        bio=profile.get("bio"),
        share_count=len(shares),
        total_views=sum(s.get("view_count") or 0 for s in shares),
        total_stars=sum(s["star_count"] for s in shares),
    )


# ---------------------------------------------------------------------------
# GET /u/{username}/shares — user's open shares
# ---------------------------------------------------------------------------

@router.get(
    "/u/{username}/shares",
    response_model=ProfileSharesResponse,
    tags=["Profiles"],
    summary="List user's public shares",
)
async def list_user_shares(
    username: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    sort: str = Query(default="recent", description="Sort: recent, views, stars"),
):
    """The shares listed on a public profile (see `_open_shares`), newest, most viewed or most starred first."""
    profile = await _public_profile(username)
    try:
        shares = await _open_shares(profile["user_id"])
    except Exception as exc:
        logger.error("Failed to fetch shares for %s: %s", username, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch shares") from exc

    shares.sort(key=_SORT_KEYS.get(sort, _SORT_KEYS["recent"]), reverse=True)
    offset = (page - 1) * limit
    rows = shares[offset:offset + limit]

    for row in rows:
        if isinstance(row.get("tags"), str):
            raw = row["tags"].strip("{}")
            row["tags"] = [t.strip().strip('"') for t in raw.split(",") if t.strip()] if raw else []
        elif not isinstance(row.get("tags"), list):
            row["tags"] = []

    return ProfileSharesResponse(
        shares=[ProfileShare(**row) for row in rows],
        page=page,
        limit=limit,
        has_more=(offset + limit) < len(shares),
    )
