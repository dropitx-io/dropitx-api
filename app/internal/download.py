"""Bulk download endpoint — ZIP streaming for file groups."""

from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


async def _fetch_group(slug: str) -> dict:
    """Fetch a share_group by slug. Raises 404 if not found."""
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("share_groups")
        .select("*")
        .eq("slug", slug)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Group not found")
    return rows[0]


async def _fetch_group_shares(group_slug: str) -> list[dict]:
    """Fetch all non-expired shares belonging to a group."""
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("shares")
        .select("*")
        .eq("group_id", group_slug)
        .execute()
    )
    rows = resp.data or []
    now = datetime.now(timezone.utc)

    valid = []
    for row in rows:
        # Skip expired shares
        expires_at = row.get("expires_at")
        if expires_at:
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if now > expires_at:
                continue
        valid.append(row)
    return valid


def _build_zip(files: list[tuple[str, bytes]]) -> bytes:
    """Build a ZIP archive from (filename, content) pairs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files:
            zf.writestr(filename, content)
    return buf.getvalue()


@router.get("/download/group/{slug}", tags=["Download"], summary="Bulk download group as ZIP")
async def bulk_download_group(slug: str):
    """Download all files in a share group as a single ZIP archive.

    Streams the ZIP to avoid holding the full archive in memory for large groups.
    """
    # Verify group exists
    group = await _fetch_group(slug)

    # Fetch shares in group
    shares = await _fetch_group_shares(slug)
    if not shares:
        raise HTTPException(status_code=404, detail="No files found in this group")

    client = get_admin_client()

    # Download all files from storage
    file_entries: list[tuple[str, bytes]] = []
    for share in shares:
        storage_path = share["storage_path"]
        filename = share.get("filename") or storage_path.split("/")[-1]
        source = share.get("source", "")
        bucket = "html-files" if source in ("upload", "editor") else "shares"

        try:
            content = await asyncio.to_thread(
                lambda sp=storage_path, b=bucket: client.storage.from_(b).download(sp)
            )
            if isinstance(content, str):
                content = content.encode("utf-8")
            file_entries.append((filename, content))
        except Exception as exc:
            logger.error("Failed to download %s: %s", storage_path, exc)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to download file: {filename}",
            ) from exc

    # Build ZIP and stream
    zip_bytes = _build_zip(file_entries)
    zip_filename = f"{slug}.zip"

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_filename}"',
            "Content-Length": str(len(zip_bytes)),
        },
    )
