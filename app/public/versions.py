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

_BUCKET = "html-files"


def _version_storage_path(slug: str, version_num: int) -> str:
    """Storage key of a version's own copy of the share content."""
    return f"versions/{slug}/{version_num}.html"


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


class RestoreResponse(BaseModel):
    """Response after restoring a version."""
    id: str
    slug: str
    version_num: int
    detail: str


@router.post("/shares/{slug}/versions/{version_num}/restore", response_model=RestoreResponse, tags=["Shares"])
async def restore_version(
    slug: str,
    version_num: int,
    user: User = Depends(get_current_user),
):
    """Restore a share to a specific version.

    Saves the current state as a new version, then overwrites the share
    with the content from the target version.
    """
    client = get_admin_client()

    # Verify ownership
    try:
        share_resp = await asyncio.to_thread(
            lambda: client.table("shares")
            .select("*")
            .eq("slug", slug)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to verify share ownership: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load share") from exc

    if not share_resp.data:
        raise HTTPException(status_code=404, detail="Share not found")

    share_row = share_resp.data[0]
    if share_row.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Fetch the target version
    try:
        version_resp = await asyncio.to_thread(
            lambda: client.table("share_versions")
            .select("*")
            .eq("share_slug", slug)
            .eq("version_num", version_num)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to fetch version %d for restore: %s", version_num, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch version") from exc

    version_rows = version_resp.data or []
    if not version_rows:
        raise HTTPException(status_code=404, detail="Version not found")

    version_row = version_rows[0]
    restored_content_text = version_row.get("content_text")
    restored_storage_path = version_row.get("storage_path")
    share_storage_path = share_row.get("storage_path") or f"shares/{slug}.html"

    # Versions saved before snapshots existed point at the live object: nothing to restore from.
    if not restored_storage_path or restored_storage_path == share_storage_path:
        raise HTTPException(status_code=409, detail="This version has no saved content to restore")

    # Save current state as a new version before restoring
    await save_version(
        slug=slug,
        content_text=share_row.get("content_text"),
        storage_path=share_row.get("storage_path"),
    )

    # Copy the version's own snapshot over the share's live object
    content_type = f"{share_row.get('mime_type') or 'text/html'}; charset=utf-8"
    try:
        content_bytes = await asyncio.to_thread(
            lambda: client.storage.from_(_BUCKET).download(restored_storage_path)
        )
        restored_size = len(content_bytes)
        await asyncio.to_thread(
            lambda: client.storage.from_(_BUCKET).upload(
                share_storage_path,
                content_bytes,
                file_options={"content-type": content_type, "upsert": "true"},
            ),
        )
    except Exception as exc:
        logger.error("Storage update failed during restore: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to restore content") from exc

    # Update the share's content_text and file_size
    update_data: dict = {"file_size": restored_size}
    if restored_content_text is not None:
        update_data["content_text"] = restored_content_text

    try:
        await asyncio.to_thread(
            lambda: client.table("shares")
            .update(update_data)
            .eq("slug", slug)
            .execute()
        )
    except Exception as exc:
        logger.error("DB update failed during restore: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update share") from exc

    return RestoreResponse(
        id=share_row["id"],
        slug=slug,
        version_num=version_num,
        detail=f"Restored to version {version_num}",
    )


async def save_version(slug: str, content_text: str | None, storage_path: str | None) -> None:
    """Save a version snapshot for a share (called on publish/update). A8.

    The live object at ``storage_path`` is copied to the version's own key, because
    the live object is overwritten by the update that follows.
    """
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

    snapshot_path = None
    if storage_path:
        candidate = _version_storage_path(slug, next_version)
        try:
            content_bytes = await asyncio.to_thread(
                lambda: client.storage.from_(_BUCKET).download(storage_path)
            )
            await asyncio.to_thread(
                lambda: client.storage.from_(_BUCKET).upload(
                    candidate,
                    content_bytes,
                    file_options={"content-type": "text/html; charset=utf-8"},
                ),
            )
            snapshot_path = candidate
        except Exception:
            logger.warning("Failed to snapshot %s for version %d of slug=%s",
                           storage_path, next_version, slug, exc_info=True)

    # Insert version record
    try:
        await asyncio.to_thread(
            lambda: client.table("share_versions").insert(
                {
                    "share_slug": slug,
                    "content_text": content_text,
                    "storage_path": snapshot_path,
                    "version_num": next_version,
                }
            ).execute()
        )
    except Exception:
        logger.warning("Failed to save version for slug=%s", slug, exc_info=True)
