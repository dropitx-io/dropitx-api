"""Version history endpoints (A8)."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.dependencies import User, get_current_user
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


class VersionItem(BaseModel):
    """A single version snapshot."""
    id: str
    share_slug: str
    content_text: str | None = None
    storage_path: str | None = None
    version_num: int
    created_at: str


class VersionListResponse(BaseModel):
    """Paginated list of versions."""
    versions: list[VersionItem]
    total: int


@router.get("/shares/{slug}/versions", response_model=VersionListResponse, tags=["Shares"])
async def list_versions(
    slug: str,
    user: User = Depends(get_current_user),
):
    """List all versions for a share. Requires auth (owner only)."""
    client = get_admin_client()

    # Verify ownership
    try:
        share_resp = await asyncio.to_thread(
            lambda: client.table("shares")
            .select("user_id")
            .eq("slug", slug)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to verify share ownership: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load versions") from exc

    if not share_resp.data:
        raise HTTPException(status_code=404, detail="Share not found")

    if share_resp.data[0].get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Fetch versions
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("share_versions")
            .select("*", count="exact")
            .eq("share_slug", slug)
            .order("version_num", desc=True)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to fetch versions: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load versions") from exc

    rows = resp.data or []
    total = resp.count or 0

    versions = [
        VersionItem(
            id=r["id"],
            share_slug=r["share_slug"],
            content_text=r.get("content_text"),
            storage_path=r.get("storage_path"),
            version_num=r["version_num"],
            created_at=r["created_at"],
        )
        for r in rows
    ]

    return VersionListResponse(versions=versions, total=total)


@router.get("/shares/{slug}/versions/{version_num}", response_model=VersionItem, tags=["Shares"])
async def get_version(
    slug: str,
    version_num: int,
    user: User = Depends(get_current_user),
):
    """Get a specific version of a share. Requires auth (owner only)."""
    client = get_admin_client()

    # Verify ownership
    try:
        share_resp = await asyncio.to_thread(
            lambda: client.table("shares")
            .select("user_id")
            .eq("slug", slug)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to verify share ownership: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load version") from exc

    if not share_resp.data:
        raise HTTPException(status_code=404, detail="Share not found")

    if share_resp.data[0].get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Fetch specific version
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("share_versions")
            .select("*")
            .eq("share_slug", slug)
            .eq("version_num", version_num)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to fetch version: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load version") from exc

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Version not found")

    r = rows[0]
    return VersionItem(
        id=r["id"],
        share_slug=r["share_slug"],
        content_text=r.get("content_text"),
        storage_path=r.get("storage_path"),
        version_num=r["version_num"],
        created_at=r["created_at"],
    )


async def save_version(slug: str, content_text: str | None, storage_path: str | None) -> None:
    """Save a version snapshot for a share (called on publish/update). A8."""
    client = get_admin_client()

    # Get current max version_num
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("share_versions")
            .select("version_num")
            .eq("share_slug", slug)
            .order("version_num", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        next_version = (rows[0]["version_num"] + 1) if rows else 1
    except Exception:
        logger.warning("Failed to get max version for slug=%s, defaulting to 1", slug)
        next_version = 1

    # Insert version record
    try:
        await asyncio.to_thread(
            lambda: client.table("share_versions").insert(
                {
                    "share_slug": slug,
                    "content_text": content_text,
                    "storage_path": storage_path,
                    "version_num": next_version,
                }
            ).execute()
        )
    except Exception:
        logger.warning("Failed to save version for slug=%s", slug, exc_info=True)
