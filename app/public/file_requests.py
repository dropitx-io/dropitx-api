"""Public file request endpoints — anonymous upload to file requests."""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, Form
from fastapi.exceptions import HTTPException as HTTPExc

from app.dependencies import get_client_ip
from core.config import settings
from core.rate_limit import check_upload_rate_limit, rate_limit_exceeded
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)
router = APIRouter()

# Allowed MIME types (reuse from upload.py)
_ALLOWED_TYPES: dict[str, str] = {
    "text/html": "html", "text/htm": "html", "text/markdown": "md", "text/plain": "txt",
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp",
    "image/svg+xml": "svg", "image/bmp": "bmp", "image/tiff": "tiff",
    "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov",
    "video/x-msvideo": "avi", "video/x-matroska": "mkv",
    "audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/wav": "wav",
    "audio/flac": "flac", "audio/aac": "aac", "audio/webm": "weba",
    "application/zip": "zip", "application/x-rar-compressed": "rar",
    "application/x-7z-compressed": "7z", "application/gzip": "gz", "application/x-tar": "tar",
}
_EXT_MAP: dict[str, str] = {
    ".html": "text/html", ".htm": "text/html", ".md": "text/markdown", ".txt": "text/plain",
    ".pdf": "application/pdf", ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".bmp": "image/bmp", ".tiff": "image/tiff", ".tif": "image/tiff",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".avi": "video/x-msvideo", ".mkv": "video/x-matroska",
    ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav",
    ".flac": "audio/flac", ".aac": "audio/aac",
    ".zip": "application/zip", ".rar": "application/x-rar-compressed",
    ".7z": "application/x-7z-compressed", ".gz": "application/gzip", ".tar": "application/x-tar",
}


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


def _is_expired(expires_at: str) -> bool:
    """Check if a request has expired."""
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) > exp
    except Exception:
        return True


@router.get("/requests/{slug}", tags=["File Requests"], summary="Get file request info (public)")
async def get_file_request_public(slug: str) -> dict:
    """Public endpoint: get info about a file request for uploaders."""
    client = get_admin_client()

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("file_requests")
            .select("id, title, description, max_files, max_file_size_mb, expires_at, require_name, require_email, is_active, upload_count")
            .eq("slug", slug)
            .execute(),
        )
    except Exception as exc:
        logger.error("Failed to fetch file request %s: %s", slug, exc)
        raise HTTPExc(status_code=500, detail="Failed to fetch file request") from exc

    if not resp.data:
        raise HTTPExc(status_code=404, detail="File request not found")

    row = resp.data[0]
    is_expired = _is_expired(row["expires_at"])

    return {
        "id": row["id"],
        "title": row.get("title"),
        "description": row.get("description"),
        "max_files": row["max_files"],
        "max_file_size_mb": row["max_file_size_mb"],
        "expires_at": row["expires_at"],
        "require_name": row["require_name"],
        "require_email": row["require_email"],
        "upload_count": row["upload_count"],
        "is_expired": is_expired or not row["is_active"],
    }


@router.post("/requests/{slug}/upload", tags=["File Requests"], summary="Upload a file to a request (anonymous)")
async def upload_to_file_request(
    request: Request,
    slug: str,
    file: UploadFile,
    uploader_name: str | None = Form(default=None),
    uploader_email: str | None = Form(default=None),
) -> dict:
    """Upload a file to a file request. No authentication required."""
    # Rate limit
    ip = get_client_ip(request)
    rate = await asyncio.to_thread(check_upload_rate_limit, ip)
    if not rate.success:
        raise rate_limit_exceeded(rate)

    client = get_admin_client()

    # Fetch the request
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("file_requests")
            .select("*")
            .eq("slug", slug)
            .execute(),
        )
    except Exception as exc:
        logger.error("Failed to fetch file request %s: %s", slug, exc)
        raise HTTPExc(status_code=500, detail="Failed to fetch file request") from exc

    if not resp.data:
        raise HTTPExc(status_code=404, detail="File request not found")

    req = resp.data[0]
    request_id = req["id"]

    # Check active and not expired
    if not req["is_active"]:
        raise HTTPExc(status_code=410, detail="This file request is no longer active")

    if _is_expired(req["expires_at"]):
        raise HTTPExc(status_code=410, detail="This file request has expired")

    # Check upload count limit
    if req["upload_count"] >= req["max_files"]:
        raise HTTPExc(status_code=400, detail=f"Maximum {req['max_files']} files allowed for this request")

    # Validate required fields
    if req["require_name"] and not uploader_name:
        raise HTTPExc(status_code=400, detail="Uploader name is required for this request")
    if req["require_email"] and not uploader_email:
        raise HTTPExc(status_code=400, detail="Uploader email is required for this request")

    # Validate file type
    content_type = _resolve_content_type(file)
    if not content_type:
        raise HTTPExc(status_code=400, detail="Unsupported file type")

    # Read and validate size
    content_bytes = await file.read()
    max_size = req["max_file_size_mb"] * 1024 * 1024
    if len(content_bytes) > max_size:
        raise HTTPExc(
            status_code=400,
            detail=f"File too large. Maximum size is {req['max_file_size_mb']} MB.",
        )
    if len(content_bytes) == 0:
        raise HTTPExc(status_code=400, detail="File is empty")

    # Generate storage path
    from core.nanoid import generate_slug as gen_slug
    file_slug = gen_slug()
    ext = _ALLOWED_TYPES[content_type]
    storage_path = f"requests/{request_id}/{file_slug}-{file.filename or f'file.{ext}'}"

    # Upload to Supabase Storage
    try:
        await asyncio.to_thread(
            lambda: client.storage.from_("html-files").upload(
                storage_path,
                content_bytes,
                file_options={"content-type": content_type, "upsert": "true"},
            ),
        )
    except Exception as exc:
        logger.error("Storage upload failed for file request %s: %s", slug, exc)
        raise HTTPExc(status_code=500, detail="Failed to upload file") from exc

    # Insert upload record
    filename = file.filename or f"upload.{ext}"
    upload_data = {
        "file_request_id": request_id,
        "storage_path": storage_path,
        "filename": filename,
        "mime_type": content_type,
        "file_size": len(content_bytes),
        "uploader_name": uploader_name,
        "uploader_email": uploader_email,
    }

    try:
        upload_resp = await asyncio.to_thread(
            lambda: client.table("file_request_uploads").insert(upload_data).execute(),
        )
    except Exception as exc:
        logger.error("DB insert failed for file request upload: %s", exc)
        # Cleanup storage
        try:
            await asyncio.to_thread(
                lambda: client.storage.from_("html-files").remove([storage_path]),
            )
        except Exception:
            pass
        raise HTTPExc(status_code=500, detail="Failed to save upload") from exc

    # Update request stats
    try:
        await asyncio.to_thread(
            lambda: client.table("file_requests")
            .update({
                "upload_count": req["upload_count"] + 1,
                "total_size_bytes": req["total_size_bytes"] + len(content_bytes),
            })
            .eq("id", request_id)
            .execute(),
        )
    except Exception as exc:
        logger.warning("Failed to update file request stats: %s", exc)

    upload_row = upload_resp.data[0] if upload_resp.data else upload_data

    return {
        "id": upload_row.get("id", ""),
        "filename": filename,
        "file_size": len(content_bytes),
        "mime_type": content_type,
        "message": "File uploaded successfully",
    }
