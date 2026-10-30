"""Multi-file upload endpoint — upload multiple files under a single share."""

from __future__ import annotations

import asyncio
import logging
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.dependencies import User, get_client_ip, get_optional_user
from app.public._share_auth import require_share_visible
from core.extract_text import extract_text_from_html, extract_text_from_markdown
from core.nanoid import generate_delete_token, generate_slug
from core.rate_limit import check_upload_rate_limit
from core.security import hash_password
from core.share_urls import share_page_url
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()

# Allowed MIME types and their extensions
_ALLOWED_TYPES: dict[str, str] = {
    "text/html": "html",
    "text/htm": "html",
    "text/markdown": "md",
    "text/plain": "md",
}

_EXT_MAP: dict[str, str] = {
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
}

_MAX_SIZE_PER_FILE = 50 * 1024 * 1024  # 50 MB
_MAX_FILES = 20  # Max files per multi-upload


class MultiFileResponse(BaseModel):
    """Response for multi-file upload."""
    slug: str
    url: str
    delete_token: str
    files: list[dict]
    file_count: int


@router.post(
    "/upload/multi",
    response_model=MultiFileResponse,
    tags=["Upload"],
    summary="Upload multiple files as a single share",
)
async def multi_upload(
    request: Request,
    files: List[UploadFile] = File(..., description="Files to upload (up to 20)"),
    title: str | None = Form(None),
    custom_slug: str | None = Form(None),
    is_private: bool = Form(False),
    password: str | None = Form(default=None, max_length=128),
    user: User | None = Depends(get_optional_user),
) -> MultiFileResponse:
    """Upload multiple HTML/Markdown files under a single share URL."""
    # Rate limit
    ip = get_client_ip(request)
    rate = await asyncio.to_thread(check_upload_rate_limit, ip)
    if not rate.success:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > _MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Maximum {_MAX_FILES} files allowed")
    if is_private and user is None:
        # A private share is readable by its owner only, so an ownerless one is unreadable.
        raise HTTPException(status_code=400, detail="Private shares require sign-in")

    client = get_admin_client()
    slug = generate_slug()
    delete_token = generate_delete_token()

    uploaded_paths: list[str] = []
    file_records: list[dict] = []
    combined_text = ""

    try:
        for idx, file in enumerate(files):
            # Validate file type
            content_type = _resolve_content_type(file)
            if not content_type:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid file type for '{file.filename}'. Only .html, .htm, and .md files are allowed.",
                )

            # Read and validate size
            content_bytes = await file.read()
            if len(content_bytes) > _MAX_SIZE_PER_FILE:
                raise HTTPException(
                    status_code=400,
                    detail=f"File '{file.filename}' too large. Maximum size is 50 MB.",
                )
            if len(content_bytes) == 0:
                raise HTTPException(status_code=400, detail=f"File '{file.filename}' is empty.")

            ext = _ALLOWED_TYPES[content_type]
            storage_path = f"shares/{slug}/{idx:03d}-{file.filename or f'file.{ext}'}"
            filename = file.filename or f"upload.{ext}"

            # Upload to Supabase Storage
            await asyncio.to_thread(
                lambda sp=storage_path, cb=content_bytes, ct=content_type: client.storage.from_("html-files").upload(
                    sp,
                    cb,
                    file_options={"content-type": ct, "upsert": "true"},
                ),
            )
            uploaded_paths.append(storage_path)

            # Extract text for search
            content_str = content_bytes.decode("utf-8", errors="replace")
            plain_text = (
                extract_text_from_html(content_str)
                if ext == "html"
                else extract_text_from_markdown(content_str)
            )
            combined_text += plain_text[:2000] + "\n"

            file_records.append({
                "share_slug": slug,
                "storage_path": storage_path,
                "filename": filename,
                "mime_type": content_type,
                "file_size": len(content_bytes),
                "sort_order": idx,
            })

        # Insert share row (backward-compatible: first file's data in main row)
        first_file = file_records[0]
        share_url = share_page_url(slug)

        await asyncio.to_thread(
            lambda: client.table("shares").insert(
                {
                    "slug": slug,
                    "user_id": user.id if user else None,
                    "storage_path": first_file["storage_path"],
                    "filename": first_file["filename"],
                    "title": title,
                    "is_private": is_private,
                    "delete_token": delete_token,
                    "content_text": combined_text[:5000],
                    "file_size": sum(f["file_size"] for f in file_records),
                    "mime_type": first_file["mime_type"],
                    "source": "upload",
                    "password_hash": hash_password(password) if password else None,
                }
            ).execute(),
        )

        # Insert share_files rows (skip first if only 1 file — backward compat)
        if len(file_records) > 1:
            share_resp = await asyncio.to_thread(
                lambda: client.table("shares")
                .select("id")
                .eq("slug", slug)
                .execute()
            )
            share_id = share_resp.data[0]["id"] if share_resp.data else None

            if share_id:
                files_to_insert = []
                for rec in file_records:
                    files_to_insert.append({
                        "share_id": share_id,
                        "storage_path": rec["storage_path"],
                        "filename": rec["filename"],
                        "mime_type": rec["mime_type"],
                        "file_size": rec["file_size"],
                        "sort_order": rec["sort_order"],
                    })

                await asyncio.to_thread(
                    lambda: client.table("share_files")
                    .insert(files_to_insert)
                    .execute()
                )

    except HTTPException:
        # Cleanup uploaded files on failure
        for path in uploaded_paths:
            await _cleanup_storage(path)
        raise
    except Exception as exc:
        logger.error("Multi-upload failed for slug=%s: %s", slug, exc)
        for path in uploaded_paths:
            await _cleanup_storage(path)
        raise HTTPException(status_code=500, detail="Failed to upload files") from exc

    return MultiFileResponse(
        slug=slug,
        url=share_url,
        delete_token=delete_token,
        files=file_records,
        file_count=len(file_records),
    )


@router.get(
    "/shares/{slug}/files",
    tags=["Upload"],
    summary="List files in a multi-file share",
)
async def list_share_files(
    slug: str,
    user: User | None = Depends(get_optional_user),
):
    """List all files attached to a share."""
    client = get_admin_client()

    # Get share ID
    share_resp = await asyncio.to_thread(
        lambda: client.table("shares")
        .select("id, is_private, user_id")
        .eq("slug", slug)
        .execute()
    )
    if not share_resp.data:
        raise HTTPException(status_code=404, detail="Share not found")

    share = share_resp.data[0]
    require_share_visible(share, user)

    # Get files (storage_path is internal and not part of the listing)
    files_resp = await asyncio.to_thread(
        lambda: client.table("share_files")
        .select("id, share_id, filename, mime_type, file_size, sort_order, created_at")
        .eq("share_id", share["id"])
        .order("sort_order")
        .execute()
    )

    return {"slug": slug, "files": files_resp.data or []}


def _resolve_content_type(file: UploadFile) -> str | None:
    """Determine valid content type from UploadFile metadata."""
    ct = (file.content_type or "").lower().split(";")[0].strip()
    if ct in _ALLOWED_TYPES:
        return ct
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
