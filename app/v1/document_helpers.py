"""Shared helpers for document endpoints — storage ops, auth checks, text extraction."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from app.dependencies import ApiKeyAuth
from core.extract_text import extract_text_from_html, extract_text_from_markdown

logger = logging.getLogger(__name__)

_STORAGE_BUCKET = "shares"
_UPLOAD_BUCKET = "html-files"
_MIME_TEXT = "text/plain; charset=utf-8"


def extract_plain_text(content: str, filename: str | None) -> str:
    """Best-effort text extraction based on file extension."""
    if filename and filename.lower().endswith(".html"):
        return extract_text_from_html(content)
    return extract_text_from_markdown(content)


def infer_mime(filename: str | None) -> str:
    """Infer MIME type from filename extension."""
    if not filename:
        return _MIME_TEXT
    low = filename.lower()
    if low.endswith(".html") or low.endswith(".htm"):
        return "text/html; charset=utf-8"
    if low.endswith(".md") or low.endswith(".markdown"):
        return "text/markdown; charset=utf-8"
    return _MIME_TEXT


def team_key_may_read(row: dict, auth: ApiKeyAuth) -> bool:
    """Team keys never read the content of private or password-protected shares."""
    return not (auth.team_id and (row.get("is_private") or row.get("password_hash")))


async def find_document(
    client, slug: str, auth: ApiKeyAuth, *, for_content: bool = False,
) -> dict:
    """Fetch a share row by slug, enforcing ownership/team access.

    With ``for_content`` the caller is about to return the share's content (or its
    revisions): a team key then gets the same 404 as for a missing slug when the share
    is private or password-protected.
    """
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("shares").select("*").eq("slug", slug).execute(),
        )
        rows = resp.data or []
    except Exception as exc:
        logger.error("Document lookup failed for %s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to find document") from exc

    if not rows:
        raise HTTPException(status_code=404, detail="Document not found")

    row = rows[0]

    if auth.team_id:
        try:
            ts = await asyncio.to_thread(
                lambda: client.table("team_shares")
                .select("id")
                .eq("share_id", row["id"])
                .eq("team_id", auth.team_id)
                .execute(),
            )
            if not ts.data:
                raise HTTPException(status_code=403, detail="Not a team document")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Team share check failed: %s", exc)
            raise HTTPException(status_code=500, detail="Access check failed") from exc
    else:
        if row.get("user_id") != auth.user_id:
            raise HTTPException(status_code=403, detail="Not your document")

    if for_content and not team_key_may_read(row, auth):
        raise HTTPException(status_code=404, detail="Document not found")

    return row


def bucket_for(row: dict) -> str:
    """Storage bucket holding a share's content: /api/upload and editor shares live in html-files."""
    return _UPLOAD_BUCKET if row.get("source") in ("upload", "editor") else _STORAGE_BUCKET


async def fetch_content(client, row: dict) -> str:
    """Download and decode a share's content from storage."""
    storage_path = row["storage_path"]
    try:
        resp = await asyncio.to_thread(
            lambda: client.storage.from_(bucket_for(row)).download(storage_path),
        )
        return resp.decode("utf-8") if isinstance(resp, bytes) else str(resp)
    except Exception as exc:
        logger.error("Content download failed for %s: %s", storage_path, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch document content") from exc
