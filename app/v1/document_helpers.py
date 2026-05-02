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


async def find_document(client, slug: str, auth: ApiKeyAuth) -> dict:
    """Fetch a share row by slug, enforcing ownership/team access."""
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

    return row


async def fetch_content(client, storage_path: str) -> str:
    """Download and decode content from Supabase Storage."""
    try:
        resp = await asyncio.to_thread(
            lambda: client.storage.from_(_STORAGE_BUCKET).download(storage_path),
        )
        return resp.decode("utf-8") if isinstance(resp, bytes) else str(resp)
    except Exception as exc:
        logger.error("Content download failed for %s: %s", storage_path, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch document content") from exc
