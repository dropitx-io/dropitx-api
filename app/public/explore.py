"""Public explore/gallery endpoints — discover trending shares."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ExploreShare(BaseModel):
    """A share card in the explore gallery."""
    id: str
    slug: str
    filename: str
    title: str | None = None
    tags: list[str] = []
    view_count: int = 0
    star_count: int = 0
    created_at: str
    user_id: str | None = None
    mime_type: str | None = None
    source: str | None = None
    # Enriched from user_profiles
    author_name: str | None = None
    author_avatar: str | None = None


class ExploreResponse(BaseModel):
    """Paginated explore results."""
    shares: list[ExploreShare]
    page: int
    limit: int
    total: int | None = None
    has_more: bool


class TagCount(BaseModel):
    """A tag with its usage count."""
    tag: str
    count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _enrich_with_authors(shares: list[dict]) -> list[dict]:
    """Add author_name and author_avatar from user_profiles."""
    user_ids = list({s["user_id"] for s in shares if s.get("user_id")})
    if not user_ids:
        return shares

    client = get_admin_client()
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("user_profiles")
            .select("user_id, display_name, avatar_url")
            .in_("user_id", user_ids)
            .execute()
        )
        profiles = {p["user_id"]: p for p in (resp.data or [])}
    except Exception:
        logger.warning("Failed to fetch user profiles for explore", exc_info=True)
        profiles = {}

    for s in shares:
        uid = s.get("user_id")
        if uid and uid in profiles:
            s["author_name"] = profiles[uid].get("display_name")
            s["author_avatar"] = profiles[uid].get("avatar_url")

    return shares


# ---------------------------------------------------------------------------
# GET /explore — paginated public shares
# ---------------------------------------------------------------------------

@router.get("/explore", tags=["Explore"], summary="Browse public shares")
async def list_explore(
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=24, ge=1, le=100, description="Results per page"),
    tag: str | None = Query(default=None, description="Filter by tag"),
    sort: Literal["trending", "recent", "views", "stars"] = Query(
        default="trending", description="Sort order"
    ),
):
    """Browse public shares with pagination, tag filter, and sort options."""
    offset = (page - 1) * limit
    client = get_admin_client()

    # Build query on public_shares view
    def _query():
        q = client.table("public_shares").select("*", count="exact")

        if tag:
            q = q.contains("tags", [tag])

        if sort == "trending":
            # Use trending_shares view for trending sort
            q2 = client.table("trending_shares").select("*", count="exact")
            if tag:
                q2 = q2.contains("tags", [tag])
            q2 = q2.range(offset, offset + limit - 1)
            return q2.execute()

        order_col = {
            "recent": "created_at",
            "views": "view_count",
            "stars": "star_count",
        }.get(sort, "created_at")

        q = q.order(order_col, desc=True)
        q = q.range(offset, offset + limit - 1)
        return q.execute()

    try:
        resp = await asyncio.to_thread(_query)
    except Exception as exc:
        logger.error("Explore query failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Explore query failed") from exc

    rows = resp.data or []
    total = resp.count

    # Normalize tags from postgres array
    for row in rows:
        if isinstance(row.get("tags"), str):
            # PostgREST returns arrays as "{a,b}" format sometimes
            raw = row["tags"].strip("{}")
            row["tags"] = [t.strip().strip('"') for t in raw.split(",") if t.strip()] if raw else []
        elif not isinstance(row.get("tags"), list):
            row["tags"] = []

    # Enrich with author info
    rows = await _enrich_with_authors(rows)

    shares = [ExploreShare(**row) for row in rows]

    return ExploreResponse(
        shares=shares,
        page=page,
        limit=limit,
        total=total,
        has_more=(offset + limit) < (total or 0),
    )


# ---------------------------------------------------------------------------
# GET /explore/tags — list all tags with counts
# ---------------------------------------------------------------------------

@router.get("/explore/tags", tags=["Explore"], summary="List all tags")
async def list_tags(
    limit: int = Query(default=50, ge=1, le=200, description="Max tags to return"),
):
    """Get all tags used across public shares with their counts."""
    client = get_admin_client()

    try:
        # Get all public shares with tags
        resp = await asyncio.to_thread(
            lambda: client.table("public_shares")
            .select("tags")
            .execute()
        )
    except Exception as exc:
        logger.error("Tags query failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Tags query failed") from exc

    rows = resp.data or []

    # Count tags
    tag_counts: dict[str, int] = {}
    for row in rows:
        tags = row.get("tags", [])
        if isinstance(tags, str):
            raw = tags.strip("{}")
            tags = [t.strip().strip('"') for t in raw.split(",") if t.strip()] if raw else []
        for t in tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    # Sort by count descending
    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:limit]

    return {
        "tags": [TagCount(tag=t, count=c) for t, c in sorted_tags],
    }


# ---------------------------------------------------------------------------
# GET /explore/trending — top trending shares
# ---------------------------------------------------------------------------

@router.get("/explore/trending", tags=["Explore"], summary="Trending shares")
async def trending_shares(
    limit: int = Query(default=10, ge=1, le=50, description="Number of trending shares"),
):
    """Get top trending shares."""
    client = get_admin_client()

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("trending_shares")
            .select("*")
            .limit(limit)
            .execute()
        )
    except Exception as exc:
        logger.error("Trending query failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Trending query failed") from exc

    rows = resp.data or []

    for row in rows:
        if isinstance(row.get("tags"), str):
            raw = row["tags"].strip("{}")
            row["tags"] = [t.strip().strip('"') for t in raw.split(",") if t.strip()] if raw else []
        elif not isinstance(row.get("tags"), list):
            row["tags"] = []

    rows = await _enrich_with_authors(rows)
    shares = [ExploreShare(**row) for row in rows]

    return JSONResponse(
        content={"shares": [s.model_dump() for s in shares]},
        headers={"cache-control": "public, max-age=60, stale-while-revalidate=120"},
    )
