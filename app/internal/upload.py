"""File upload endpoint — HTML/Markdown file sharing."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.exceptions import HTTPException

from app.dependencies import User, get_client_ip, get_optional_user
from core.config import settings
from core.extract_text import extract_text_from_html, extract_text_from_markdown
from core.nanoid import generate_delete_token, generate_slug
from core.rate_limit import check_upload_rate_limit
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()

# Allowed MIME types and their extensions
_ALLOWED_TYPES: dict[str, str] = {
    "text/html": "html",
    "text/htm": "html",
    "text/markdown": "md",
    "text/plain": "md",  # .md files often uploaded as text/plain
}

# Extension-to-content_type mapping for fallback detection
_EXT_MAP: dict[str, str] = {
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
}

_MAX_SIZE = 50 * 1024 * 1024  # 50 MB


class UploadResponse:
    """Response model for upload endpoint."""

    def __init__(self, slug: str, url: str, filename: str, deleteToken: str):
        self.slug = slug
        self.url = url
        self.filename = filename
        self.deleteToken = deleteToken

    def dict(self) -> dict:
        return {
            "slug": self.slug,
            "url": self.url,
            "filename": self.filename,
            "deleteToken": self.deleteToken,
        }


@router.post("/upload", tags=["Upload"])
async def upload(
    request: Request,
    file: UploadFile,
    user: User | None = Depends(get_optional_user),
) -> dict:
    """Upload an HTML or Markdown file. Optional auth for linking to user."""
    # Rate limit
    ip = get_client_ip(request)
    rate = await asyncio.to_thread(check_upload_rate_limit, ip)
    if not rate.success:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Validate file type
    content_type = _resolve_content_type(file)
    if not content_type:
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only .html, .htm, and .md files are allowed.",
        )

    # Read and validate size
    content_bytes = await file.read()
    if len(content_bytes) > _MAX_SIZE:
        raise HTTPException(
            status_code=400, detail="File too large. Maximum size is 50 MB."
        )
    if len(content_bytes) == 0:
        raise HTTPException(status_code=400, detail="File is empty.")

    # Generate identifiers
    slug = generate_slug()
    ext = _ALLOWED_TYPES[content_type]
    storage_path = f"shares/{slug}.{ext}"
    delete_token = generate_delete_token()

    # Upload to Supabase Storage
    client = get_admin_client()
    try:
        await asyncio.to_thread(
            lambda: client.storage.from_("html-files").upload(
                storage_path,
                content_bytes,
                file_options={"content-type": content_type, "upsert": "true"},
            ),
        )
    except Exception as exc:
        logger.error("Storage upload failed for slug=%s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to upload file") from exc

    # Extract plain text for search
    content_str = content_bytes.decode("utf-8", errors="replace")
    plain_text = (
        extract_text_from_html(content_str)
        if ext == "html"
        else extract_text_from_markdown(content_str)
    )

    # Insert into shares table
    share_url = f"{settings.supabase_url}/storage/v1/object/public/html-files/{storage_path}"
    filename = file.filename or f"upload.{ext}"

    try:
        await asyncio.to_thread(
            lambda: client.table("shares").insert(
                {
                    "slug": slug,
                    "user_id": user.id if user else None,
                    "storage_path": storage_path,
                    "filename": filename,
                    "title": None,
                    "is_private": False,
                    "delete_token": delete_token,
                    "plain_text": plain_text[:5000],
                    "content_type": ext,
                }
            ).execute(),
        )
    except Exception as exc:
        logger.error("DB insert failed for slug=%s: %s", slug, exc)
        # Compensating transaction: remove uploaded file
        await _cleanup_storage(storage_path)
        raise HTTPException(status_code=500, detail="Failed to save share") from exc

    resp = UploadResponse(
        slug=slug,
        url=share_url,
        filename=filename,
        deleteToken=delete_token,
    )
    return resp.dict()


def _resolve_content_type(file: UploadFile) -> str | None:
    """Determine valid content type from UploadFile metadata."""
    # Check content_type first
    ct = (file.content_type or "").lower().split(";")[0].strip()
    if ct in _ALLOWED_TYPES:
        return ct

    # Fallback: check filename extension
    if file.filename:
        fname = file.filename.lower()
        for ext, mapped_ct in _EXT_MAP.items():
            if fname.endswith(ext):
                return mapped_ct

    return None


async def _cleanup_storage(storage_path: str) -> None:
    """Remove uploaded file from storage (compensating transaction)."""
    try:
        client = get_admin_client()
        await asyncio.to_thread(
            lambda: client.storage.from_("html-files").remove([storage_path]),
        )
    except Exception:
        logger.warning(
            "Failed to cleanup storage path=%s", storage_path, exc_info=True
        )
