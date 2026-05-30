"""Version history endpoints — list revisions, restore a revision."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.dependencies import ApiKeyAuth, get_api_key
from app.v1.document_helpers import find_document, fetch_content, infer_mime
from models.share import ShareRevision, RevisionListResponse
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents/{slug}/revisions", tags=["Documents"])


class RestoreResponse(BaseModel):
    id: str
    slug: str
    revision: int
    detail: str


async def _get_next_revision(client, share_id: str) -> int:
    """Get the next revision number for a share."""
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("share_revisions")
            .select("revision")
            .eq("share_id", share_id)
            .order("revision", desc=True)
            .limit(1)
            .execute(),
        )
        rows = resp.data or []
        return (rows[0]["revision"] + 1) if rows else 1
    except Exception as exc:
        logger.error("Failed to get next revision for share %s: %s", share_id, exc)
        return 1


async def save_revision(
    share_id: str,
    content: str,
    filename: str | None = None,
    title: str | None = None,
) -> int:
    """Save a content revision for a share. Returns the revision number."""
    client = get_admin_client()
    revision = await _get_next_revision(client, share_id)

    try:
        await asyncio.to_thread(
            lambda: client.table("share_revisions").insert({
                "share_id": share_id,
                "revision": revision,
                "content": content,
                "filename": filename,
                "title": title,
            }).execute(),
        )
        logger.info("Saved revision %d for share %s", revision, share_id)
    except Exception as exc:
        logger.error("Failed to save revision for share %s: %s", share_id, exc)
        # Non-fatal: log and continue
        return -1

    return revision


@router.get("", response_model=RevisionListResponse, summary="List revisions")
async def list_revisions(
    slug: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    auth: ApiKeyAuth = Depends(get_api_key),
) -> RevisionListResponse:
    """List all revisions for a document, newest first."""
    client = get_admin_client()
    row = await find_document(client, slug, auth)
    share_id = row["id"]
    offset = (page - 1) * limit

    try:
        # Get total count
        count_resp = await asyncio.to_thread(
            lambda: client.table("share_revisions")
            .select("id", count="exact")
            .eq("share_id", share_id)
            .execute(),
        )
        total = count_resp.count if count_resp.count is not None else 0

        # Get page of revisions
        resp = await asyncio.to_thread(
            lambda: client.table("share_revisions")
            .select("*")
            .eq("share_id", share_id)
            .order("revision", desc=True)
            .range(offset, offset + limit - 1)
            .execute(),
        )
        rows = resp.data or []
    except Exception as exc:
        logger.error("Failed to list revisions for %s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to list revisions") from exc

    revisions = [ShareRevision(**r) for r in rows]
    return RevisionListResponse(revisions=revisions, total=total)


@router.get("/{revision}", response_model=ShareRevision, summary="Get a specific revision")
async def get_revision(
    slug: str,
    revision: int,
    auth: ApiKeyAuth = Depends(get_api_key),
) -> ShareRevision:
    """Get a specific revision by number."""
    client = get_admin_client()
    row = await find_document(client, slug, auth)
    share_id = row["id"]

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("share_revisions")
            .select("*")
            .eq("share_id", share_id)
            .eq("revision", revision)
            .execute(),
        )
        rows = resp.data or []
    except Exception as exc:
        logger.error("Failed to fetch revision %d for %s: %s", revision, slug, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch revision") from exc

    if not rows:
        raise HTTPException(status_code=404, detail="Revision not found")

    return ShareRevision(**rows[0])


@router.post("/{revision}/restore", response_model=RestoreResponse, summary="Restore a revision")
async def restore_revision(
    slug: str,
    revision: int,
    auth: ApiKeyAuth = Depends(get_api_key),
) -> RestoreResponse:
    """Restore a document to a specific revision.

    This creates a new revision with the restored content, and updates
    the share's storage and content_text.
    """
    client = get_admin_client()
    row = await find_document(client, slug, auth)
    share_id = row["id"]

    # Fetch the target revision
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("share_revisions")
            .select("*")
            .eq("share_id", share_id)
            .eq("revision", revision)
            .execute(),
        )
        rows = resp.data or []
    except Exception as exc:
        logger.error("Failed to fetch revision %d for restore: %s", revision, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch revision") from exc

    if not rows:
        raise HTTPException(status_code=404, detail="Revision not found")

    rev_row = rows[0]
    restored_content = rev_row["content"]

    # Save current state as a new revision before overwriting
    current_content = await fetch_content(client, row["storage_path"])
    await save_revision(
        share_id,
        current_content,
        filename=row.get("filename"),
        title=row.get("title"),
    )

    # Upload restored content to storage
    try:
        await asyncio.to_thread(
            lambda: client.storage.from_("shares").update(
                path=row["storage_path"],
                file=restored_content.encode("utf-8"),
                file_options={"content-type": infer_mime(row.get("filename"))},
            ),
        )
    except Exception as exc:
        logger.error("Storage update failed during restore: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to restore content") from exc

    # Update share metadata
    from core.extract_text import extract_text_from_html, extract_text_from_markdown

    filename = rev_row.get("filename") or row.get("filename")
    if filename and filename.lower().endswith(".html"):
        plain_text = extract_text_from_html(restored_content)
    else:
        plain_text = extract_text_from_markdown(restored_content)

    new_title = rev_row.get("title") or row.get("title")
    try:
        await asyncio.to_thread(
            lambda: client.table("shares").update({
                "content_text": plain_text[:5000],
                "file_size": len(restored_content.encode("utf-8")),
                "title": new_title,
                "filename": filename,
            }).eq("id", share_id).execute(),
        )
    except Exception as exc:
        logger.error("DB update failed during restore: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update share") from exc

    # Save the restored content as a new revision
    new_rev = await save_revision(share_id, restored_content, filename=filename, title=new_title)

    return RestoreResponse(
        id=share_id,
        slug=slug,
        revision=new_rev,
        detail=f"Restored to revision {revision}",
    )
